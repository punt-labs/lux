"""Machine-local opt-in terminal daemon: enable, disable, status and restart."""

from __future__ import annotations

from collections.abc import Callable

import typer

from punt_lux.pty.service import TerminalService


class TerminalCommands:
    @staticmethod
    def _action(operation: Callable[[], str]) -> None:
        try:
            typer.echo(operation())
        except RuntimeError as error:
            typer.echo(str(error), err=True)
            raise typer.Exit(1) from error

    @staticmethod
    def enable() -> None:
        """Enable on this machine: install/start the supervised owner and launcher."""
        TerminalCommands._action(TerminalService().enable)

    @staticmethod
    def disable() -> None:
        """Disable here: stops held programs and removes supervisor registration."""
        TerminalCommands._action(TerminalService().disable)

    @staticmethod
    def restart() -> None:
        """Explicitly restart the owner; this ends its held programs."""
        TerminalCommands._action(TerminalService().restart)

    @staticmethod
    def status() -> None:
        """Read this machine's supervisor state without starting anything."""
        service = TerminalService()
        typer.echo("luxd-pty running" if service.is_active else "luxd-pty not running")


terminal_app = typer.Typer(help="Manage this machine's Terminal launcher.")
terminal_app.command("enable")(TerminalCommands.enable)
terminal_app.command("install", hidden=True)(TerminalCommands.enable)
terminal_app.command("disable")(TerminalCommands.disable)
terminal_app.command("restart")(TerminalCommands.restart)
terminal_app.command("status")(TerminalCommands.status)
