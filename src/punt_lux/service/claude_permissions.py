"""Lux's permission rules in a checkout's project or local settings.

``lux enable`` is the operator's explicit opt-in, so it -- not plugin startup
-- grants Claude Code permission to call lux's MCP tools and slash commands
without a prompt. The rules land in the checkout's
``.claude/settings.json`` or ``.claude/settings.local.json``, never the user-global
``~/.claude/settings.json``, and ``lux disable`` removes exactly the same set
(punt-kit ``permissions.md`` §6). The ``lux-dev`` plugin's rules are never
granted: maintainers add them by hand.
"""

from __future__ import annotations

import sys
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Literal, Self, final

from punt_lux.service.permission_settings import (
    PermissionChange,
    PermissionEdit,
    PermissionSettings,
)

__all__ = ["PermissionChange", "ProjectPermissions"]


@final
class ProjectPermissions:
    """Add or remove :data:`LUX_RULES` in one checkout's scoped settings.

    The read-modify-write holds the tool-agnostic
    ``.settings.json.punt-import.lock`` (other punt tools edit the same file),
    follows symlinks to a user-selected settings target, inserts in order without
    reordering existing entries, and does not write when nothing changes.
    Every other key and rule in the file is preserved.
    """

    __slots__ = ("_settings",)

    _settings: PermissionSettings

    def __new__(
        cls, root: Path | str, scope: Literal["project", "local"] = "project"
    ) -> Self:
        self = super().__new__(cls)
        self._settings = PermissionSettings(root, scope)
        return self

    def grant(self) -> PermissionChange:
        """Insert each missing Lux rule; return the rules added."""
        return self._settings.apply(add=True)

    def revoke(self) -> PermissionChange:
        """Remove every lux rule; return the rules removed."""
        return self._settings.apply(add=False)

    def report(self, *, add: bool, quiet: bool) -> None:
        """Apply the rule change and report errors even in quiet mode."""
        change = self._settings.apply(add=add)
        if not quiet or change.error:
            for line in change.lines("added to" if add else "removed from"):
                sys.stderr.write(f"{line}\n")
        if change.error:
            raise SystemExit(1)

    def prepare(self, *, add: bool) -> AbstractContextManager[PermissionEdit]:
        """Validate and plan a settings update while holding the settings lock."""
        return self._settings.prepare(add=add)
