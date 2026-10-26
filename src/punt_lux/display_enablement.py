"""``lux enable`` / ``lux disable``: repo permissions, then the display mode."""

from __future__ import annotations

from typing import TYPE_CHECKING

import typer

from punt_lux.claude_permissions import ProjectPermissions
from punt_lux.config import ConfigManager

if TYPE_CHECKING:
    from punt_lux.cli._shared import OutputFlags

__all__ = ["set_display"]


def set_display(flags: OutputFlags, *, on: bool) -> None:
    """Grant (``on``) or revoke lux's repo permissions, then write the mode.

    Permissions go first, so a refused settings file exits 1 with the display
    mode unchanged.
    """
    flags.apply_logging()
    manager = ConfigManager()
    ProjectPermissions(manager.path.parent.parent).report(add=on, quiet=flags.quiet)
    manager.write_field("display", "y" if on else "n")
    if flags.quiet:
        return
    if flags.json:
        typer.echo('{"enabled": true}' if on else '{"enabled": false}')
    else:
        typer.echo("Lux display enabled." if on else "Lux display disabled.")
