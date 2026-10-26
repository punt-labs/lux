"""``lux enable`` / ``lux disable``: repo permissions, then the display mode."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

import typer

from punt_lux.claude_permissions import ProjectPermissions
from punt_lux.config import ConfigManager

if TYPE_CHECKING:
    from punt_lux.cli._shared import OutputFlags

__all__ = ["DisplayEnablement"]


@final
class DisplayEnablement:
    """Turn lux on or off for the current repo, permissions first."""

    _flags: OutputFlags
    __slots__ = ("_flags",)

    def __new__(cls, flags: OutputFlags) -> Self:
        self = super().__new__(cls)
        self._flags = flags
        return self

    def apply(self, *, on: bool) -> None:
        """Grant (``on``) or revoke lux's repo permissions, then write the mode.

        A refused settings file exits 1 with the display mode unchanged.
        """
        flags = self._flags
        flags.apply_logging()
        manager = ConfigManager()
        root = manager.path.parent.parent
        ProjectPermissions(root).report(add=on, quiet=flags.quiet)
        manager.write_field("display", "y" if on else "n")
        if flags.quiet:
            return
        if flags.json:
            typer.echo('{"enabled": true}' if on else '{"enabled": false}')
        else:
            typer.echo("Lux display enabled." if on else "Lux display disabled.")
