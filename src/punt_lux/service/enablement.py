"""Repository integration shared by the CLI and the MCP server."""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

from punt_lux.service.activation_file import ActivationFile
from punt_lux.service.claude_import import ClaudeImport
from punt_lux.service.display_preference import DisplayPreference
from punt_lux.service.enablement_files import EnablementFiles, VendoredGuide
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
        if action == "enable":
            notice = self._enable(refresh=refresh, clear_opt_out=clear_opt_out)
            return replace(self.checkout.state(), notice=notice)
        self._disable(opt_out=opt_out)
        return self.checkout.state()

    @property
    def _opting_out(self) -> Path:
        return self.checkout.root / SHARED / "opt-out"

    @property
    def _muted(self) -> Path:
        return self.checkout.root / PERSONAL / "disabled"

    @property
    def _inherits_shared(self) -> bool:
        enabled = self.checkout.root / SHARED / "enabled"
        return self.scope == "local" and enabled.exists()

    def _enable(self, *, refresh: bool, clear_opt_out: bool) -> str | None:
        opting_out = self._opting_out
        if opting_out.exists() and not clear_opt_out:
            msg = f"Lux opted out by {opting_out}; use --scope project --clear-opt-out"
            raise ValueError(msg)
        if self._inherits_shared:
            return self._enable_inherited(refresh=refresh)
        guide = self._guide
        self._check_personal_paths(guide)
        content = guide.prepare(refresh=refresh)
        with self._files.integration(add=True) as batch:
            guide.deposit(content, batch=batch)
            batch.mark(self.directory / "enabled")
            if self.scope == "local":
                self._unmute()
            if clear_opt_out:
                opting_out.unlink(missing_ok=True)
        self._migrate_display()
        return None

    def _enable_inherited(self, *, refresh: bool) -> str | None:
        notice = None
        with EnablementFiles.writes() as batch:
            if refresh:
                guide = self._guide
                if self.imports.references(guide.guide):
                    self.checkout.require_private(*guide.paths, self._muted)
                    guide.deposit(guide.prepare(refresh=True), batch=batch)
                else:
                    notice = (
                        "No active local Lux guide to refresh; guide files unchanged."
                    )
            self._unmute()
        return notice

    def _disable(self, *, opt_out: bool) -> None:
        self._check_personal_paths()
        self._files.remove()
        (self.directory / "enabled").unlink(missing_ok=True)
        with EnablementFiles.writes() as batch:
            if self._inherits_shared:
                batch.mark(self._muted)
            if opt_out:
                batch.mark(self._opting_out)

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

    @property
    def _files(self) -> EnablementFiles:
        return EnablementFiles(self.imports, self.checkout.root, self.scope)

    @property
    def _guide(self) -> VendoredGuide:
        return VendoredGuide(self.directory)
