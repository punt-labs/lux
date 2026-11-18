"""Supervisor commands share one composition point, never a remote surface."""

from __future__ import annotations

from typing import TYPE_CHECKING

from punt_lux.cli.display_service import display_app
from punt_lux.cli.hub import hub_app
from punt_lux.cli.terminal import terminal_app

if TYPE_CHECKING:
    import typer


class ServiceCommands:
    @staticmethod
    def register(app: typer.Typer) -> None:
        app.add_typer(hub_app, name="hub")
        app.add_typer(display_app, name="display")
        app.add_typer(terminal_app, name="terminal")
