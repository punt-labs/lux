"""Repository integration shared by the CLI and the MCP server."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, replace
from importlib.resources import files
from pathlib import Path
from typing import Literal

from punt_lux.service.activation_file import ActivationFile
from punt_lux.service.claude_import import ClaudeImport
from punt_lux.service.claude_permissions import ProjectPermissions
from punt_lux.service.display_preference import DisplayPreference
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
        guide = (self.directory / "CLAUDE.md").relative_to(root).as_posix()
        return ClaudeImport(ActivationFile(root / host), f"@{guide}".encode())

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
        notice = None
        if action == "enable":
            notice = self._enable(refresh=refresh, clear_opt_out=clear_opt_out)
        else:
            self._disable(opt_out=opt_out)
        return replace(self.checkout.state(), notice=notice)

    @property
    def _opting_out(self) -> Path:
        return self.checkout.root / SHARED / "opt-out"

    @property
    def _muted(self) -> Path:
        return self.checkout.root / PERSONAL / "disabled"

    @property
    def _inherits_shared(self) -> bool:
        return (
            self.scope == "local" and (self.checkout.root / SHARED / "enabled").exists()
        )

    def _enable(self, *, refresh: bool, clear_opt_out: bool) -> str | None:
        opting_out = self._opting_out
        if opting_out.exists() and not clear_opt_out:
            msg = f"Lux opted out by {opting_out}; use --scope project --clear-opt-out"
            raise ValueError(msg)
        if self._inherits_shared:
            return self._enable_inherited(refresh=refresh)
        guide = VendoredGuide(self.directory)
        self._check_personal_paths(guide)
        content = guide.prepare(refresh=refresh)
        self._edit_integration(add=True)
        guide.deposit(content)
        self._mark(self.directory / "enabled")
        if self.scope == "local":
            self._unmute()
        if clear_opt_out:
            opting_out.unlink(missing_ok=True)
        self._migrate_display()
        return None

    def _enable_inherited(self, *, refresh: bool) -> str | None:
        if refresh:
            guide = VendoredGuide(self.directory)
            if not self.imports.references(guide.guide):
                return "No active local Lux guide to refresh; local files unchanged."
            self.checkout.require_private(*guide.paths, self._muted)
            guide.deposit(guide.prepare(refresh=True))
        self._unmute()
        return None

    def _disable(self, *, opt_out: bool) -> None:
        self._check_personal_paths()
        self._edit_integration(add=False)
        (self.directory / "enabled").unlink(missing_ok=True)
        if self._inherits_shared:
            self._mark(self._muted)
        if opt_out:
            self._mark(self._opting_out)

    def _migrate_display(self) -> None:
        try:
            DisplayPreference(self.checkout.root).migrate()
        except (OSError, ValueError) as exc:
            logger.warning("Could not migrate the legacy display preference: %s", exc)

    def _unmute(self) -> None:
        muted = self._muted
        if muted.exists(follow_symlinks=False):
            self.checkout.require_private(muted)
            muted.unlink()

    def _check_personal_paths(self, guide: VendoredGuide | None = None) -> None:
        if self.scope == "project":
            return
        settings = ActivationFile(self.checkout.root / ".claude/settings.local.json")
        host = self.imports.host
        hosts = (host.path, host.lock_path, settings.path, settings.lock_path)
        markers = (self.directory / "enabled", self._muted)
        guide_paths = () if guide is None else guide.paths
        self.checkout.require_private(*hosts, *markers, *guide_paths)

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

    @property
    def paths(self) -> tuple[Path, Path]:
        return self.guide.path, self.inventory.path

    def _check_refresh(self) -> None:
        if (recorded := self.inventory.read()) is None:
            return
        previous: object = json.loads(recorded)
        if previous not in ([], ["CLAUDE.md"]):
            msg = f"Unexpected vendored paths in {self.inventory.path}"
            raise ValueError(msg)
        if previous == [] and self.guide.read() is not None:
            msg = f"Unowned guide path is occupied: {self.guide.path}"
            raise ValueError(msg)

    def prepare(self, *, refresh: bool) -> bytes | None:
        if refresh:
            self._check_refresh()
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
