"""Plan and apply the file changes for Lux repository integration."""

from __future__ import annotations

import json
import logging
from collections.abc import Generator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

from punt_lux.service.activation_file import ActivationFile
from punt_lux.service.claude_import import ClaudeImport
from punt_lux.service.claude_permissions import ProjectPermissions
from punt_lux.service.repo_activation import Scope

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class EnablementFiles:
    imports: ClaudeImport
    root: Path
    scope: Scope

    class WriteBatch:
        __slots__ = ("_undo",)
        _undo: ExitStack

        def __new__(cls) -> EnablementFiles.WriteBatch:
            self = super().__new__(cls)
            self._undo = ExitStack()
            return self

        def mark(self, path: Path) -> None:
            if not path.exists():
                self.write(ActivationFile(path), b"")

        def write(self, file: ActivationFile, data: bytes | None) -> None:
            if data is None:
                return
            target = ActivationFile(file.path.resolve())
            original = target.read()
            if original == data:
                return
            target.write(data)
            self._undo.callback(self._restore, target, original)

        @staticmethod
        def _restore(target: ActivationFile, original: bytes | None) -> None:
            if original is None:
                target.path.unlink(missing_ok=True)
            else:
                target.write(original)

        @classmethod
        @contextmanager
        def writes(cls) -> Generator[EnablementFiles.WriteBatch]:
            with (batch := cls())._undo as undo:
                yield batch
                undo.pop_all()

    @contextmanager
    def integration(self, *, add: bool) -> Generator[WriteBatch]:
        with (
            self.imports.prepare(add=add) as data,
            ProjectPermissions(self.root, self.scope).prepare(add=add) as edit,
            self.WriteBatch.writes() as batch,
        ):
            batch.write(self.imports.host, data)
            batch.write(edit.file, edit.data)
            yield batch


@dataclass(frozen=True, slots=True)
class VendoredGuide:
    directory: Path

    @property
    def guide(self) -> ActivationFile:
        return ActivationFile(self.directory / "CLAUDE.md")

    @property
    def inventory(self) -> ActivationFile:
        return ActivationFile(self.directory / ".vendored-manifest")

    @property
    def paths(self) -> tuple[Path, Path]:
        return self.guide.path, self.inventory.path

    def _check_refresh(self, recorded: bytes, original: bytes | None) -> None:
        previous: object = json.loads(recorded)
        if previous not in ([], ["CLAUDE.md"]):
            msg = f"Unexpected vendored paths in {self.inventory.path}"
            raise ValueError(msg)
        if previous == [] and original is not None:
            msg = f"Unowned guide path is occupied: {self.guide.path}"
            raise ValueError(msg)

    def prepare(self, *, refresh: bool) -> bytes | None:
        original = self.guide.read()
        if original is not None and not refresh:
            return None
        recorded = self.inventory.read()
        if refresh and recorded is not None:
            self._check_refresh(recorded, original)
        content = files("punt_lux.service").joinpath("lux-guide.md").read_bytes()
        if original not in (None, content) and recorded is None:
            logger.warning("Replacing previously deposited guide %s", self.guide.path)
        return content

    def deposit(
        self, content: bytes | None, *, batch: EnablementFiles.WriteBatch
    ) -> None:
        if content is not None:
            batch.write(self.guide, content)
            batch.write(self.inventory, b'["CLAUDE.md"]\n')
