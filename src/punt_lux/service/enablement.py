"""Repository integration shared by the CLI and the MCP server."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Literal

from punt_lux.service.activation_file import ActivationFile
from punt_lux.service.claude_import import ClaudeImport
from punt_lux.service.claude_permissions import ProjectPermissions
from punt_lux.service.config import (
    DEFAULT_CONFIG_PATH,
    ConfigManager,
)
from punt_lux.service.repo_activation import (
    PERSONAL,
    SHARED,
    ActivationState,
    Checkout,
    Scope,
)

logger = logging.getLogger(__name__)

type Action = Literal["enable", "disable"]


@dataclass(frozen=True, slots=True)
class Enablement:
    checkout: Checkout
    scope: Scope

    @property
    def directory(self) -> Path:
        return self.checkout.root / (SHARED if self.scope == "project" else PERSONAL)

    @property
    def imports(self) -> ClaudeImport:
        root = self.checkout.root
        host = "CLAUDE.md" if self.scope == "project" else "CLAUDE.local.md"
        guide = (self.directory / "CLAUDE.md").relative_to(root)
        return ClaudeImport(
            ActivationFile(root / host), f"@{guide.as_posix()}".encode()
        )

    def apply(
        self,
        action: Action,
        *,
        refresh: bool = False,
        opt_out: bool = False,
        clear_opt_out: bool = False,
    ) -> ActivationState:
        if (opt_out or clear_opt_out) and self.scope != "project":
            msg = "Opt-out changes require --scope project"
            raise ValueError(msg)
        if self.checkout.root == Path.home().resolve():
            msg = "The home directory contains user-global Claude settings"
            raise ValueError(msg)
        root = self.checkout.root
        opting_out = root / SHARED / "opt-out"
        shared = (root / SHARED / "enabled").exists()
        muted = root / PERSONAL / "disabled"
        if action == "enable":
            if opting_out.exists() and not clear_opt_out:
                msg = (
                    f"Lux is opted out by {opting_out}; "
                    "use --scope project --clear-opt-out"
                )
                raise ValueError(msg)
            if self.scope == "local" and shared:
                self._unmute(muted)
                return self.checkout.state()
            guide = self._prepare_guide(refresh=refresh)
            self._check_personal_paths(guide)
            content = guide.prepare(refresh=refresh)
            self._edit_integration(add=True)
            guide.deposit(content)
            self._mark(self.directory / "enabled")
            if self.scope == "local":
                self._unmute(muted)
            if clear_opt_out:
                opting_out.unlink(missing_ok=True)
            self._migrate_display()
        else:
            self._check_personal_paths()
            self._edit_integration(add=False)
            (self.directory / "enabled").unlink(missing_ok=True)
            if self.scope == "local" and shared:
                self.checkout.require_private(muted)
                self._mark(muted)
            if opt_out:
                self._mark(opting_out)
        return self.checkout.state()

    def _migrate_display(self) -> None:
        root = self.checkout.root
        try:
            main = Checkout.resolve(root, main=True)
            local = main.root / DEFAULT_CONFIG_PATH
            legacy = ConfigManager.for_display(root, main=main.root)
            if not local.exists() and legacy.path.is_file():
                main.require_private(local)
                ConfigManager(local).write_field("display", legacy.read().display)
        except (OSError, ValueError) as exc:
            logger.warning("Could not migrate the legacy display preference: %s", exc)

    def _unmute(self, muted: Path) -> None:
        if muted.exists() or muted.is_symlink():
            self.checkout.require_private(muted)
            muted.unlink()

    def _prepare_guide(self, *, refresh: bool) -> VendoredGuide:
        guide = VendoredGuide(self.directory)
        if refresh:
            guide.check_refresh()
        return guide

    def _check_personal_paths(self, guide: VendoredGuide | None = None) -> None:
        if self.scope == "project":
            return
        root = self.checkout.root
        settings = ActivationFile(root / ".claude/settings.local.json")
        host = self.imports.host
        paths: tuple[Path, ...] = (
            host.path,
            host.lock_path,
            settings.path,
            settings.lock_path,
            self.directory / "enabled",
            self.directory / "disabled",
        )
        if guide is not None:
            paths = (*paths, guide.guide.path, guide.inventory.path)
        self.checkout.require_private(*paths)

    def _edit_integration(self, *, add: bool) -> None:
        imports = self.imports
        permissions = ProjectPermissions(self.checkout.root, self.scope)
        with imports.prepare(add=add) as data, permissions.prepare(add=add) as edit:
            if data is not None:
                imports.host.write(data)
            edit.commit()

    @staticmethod
    def _mark(path: Path) -> None:
        if not path.exists():
            ActivationFile(path).write(b"")


@dataclass(frozen=True, slots=True)
class VendoredGuide:
    directory: Path

    @property
    def guide(self) -> ActivationFile:
        return ActivationFile(self.directory / "CLAUDE.md")

    @property
    def inventory(self) -> ActivationFile:
        return ActivationFile(self.directory / ".vendored-manifest")

    def check_refresh(self) -> None:
        recorded = self.inventory.read()
        if recorded is None:
            return
        previous: object = json.loads(recorded)
        if previous not in ([], ["CLAUDE.md"]):
            msg = f"Unexpected vendored paths in {self.inventory.path}"
            raise ValueError(msg)
        if previous == [] and self.guide.read() is not None:
            msg = f"Unowned guide path is occupied: {self.guide.path}"
            raise ValueError(msg)

    def prepare(self, *, refresh: bool) -> bytes | None:
        original = self.guide.read()
        if original is not None and not refresh:
            return None
        content = files("punt_lux.service").joinpath("lux-guide.md").read_bytes()
        if original not in (None, content) and self.inventory.read() is None:
            logger.warning("Replacing previously deposited guide %s", self.guide.path)
        return content

    def deposit(self, content: bytes | None) -> None:
        if content is None:
            return
        self.guide.write(content)
        self.inventory.write(b'["CLAUDE.md"]\n')
