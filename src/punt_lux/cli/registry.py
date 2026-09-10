"""Register every noun sub-app and top-level admin verb onto the CLI.

``__main__`` composes exactly one dependency here instead of one per
sub-app — the sub-apps' own modules (``hub``, ``session``, ``scene``, ...)
stay untouched; this module only wires them onto the shared ``app``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.cli import (
    display_link as _display_link,  # noqa: F401  # pyright: ignore[reportUnusedImport]
)
from punt_lux.cli.beads import beads as beads_command
from punt_lux.cli.callback import callback_app
from punt_lux.cli.display_service import display_app
from punt_lux.cli.error import error_app
from punt_lux.cli.event import event_app
from punt_lux.cli.frame import frame_app
from punt_lux.cli.hub import hub_app
from punt_lux.cli.menu import menu_app
from punt_lux.cli.plugin import (
    _PLUGIN_ID,
    install as plugin_install,
    uninstall as plugin_uninstall,
)
from punt_lux.cli.scene import scene_app
from punt_lux.cli.session import session_app

if TYPE_CHECKING:
    import typer

__all__ = ["PLUGIN_ID", "register_subcommands"]

PLUGIN_ID = _PLUGIN_ID


@final
class _SubcommandRegistry:
    """Attach every noun sub-app and admin verb onto a ``typer.Typer`` app."""

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    def __call__(self, app: typer.Typer) -> None:
        """Wire every noun sub-app and admin verb onto ``app``."""
        app.add_typer(hub_app, name="hub")
        app.add_typer(session_app, name="session")
        app.add_typer(scene_app, name="scene")
        app.add_typer(frame_app, name="frame")
        app.add_typer(menu_app, name="menu")
        app.add_typer(display_app, name="display")
        app.add_typer(event_app, name="event")
        app.add_typer(error_app, name="error")
        app.add_typer(callback_app, name="callback")
        app.command("beads")(beads_command)
        app.command()(plugin_install)
        app.command()(plugin_uninstall)


register_subcommands: _SubcommandRegistry = _SubcommandRegistry()
