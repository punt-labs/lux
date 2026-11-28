"""Machine-local opt-in terminal daemon: install, uninstall, status and restart."""

from __future__ import annotations

from collections.abc import Callable

import typer

from punt_lux.service.terminal_service import TerminalService


class TerminalCommands:
    @staticmethod
    def _action(operation: Callable[[], str]) -> None:
        try:
            typer.echo(operation())
        except RuntimeError as error:
            typer.echo(str(error), err=True)
            raise typer.Exit(1) from error

    @staticmethod
    def install() -> None:
        """Enable on this machine: install/start the supervised owner and launcher."""
        TerminalCommands._action(TerminalService().enable)

    @staticmethod
    def uninstall() -> None:
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
terminal_app.command("install")(TerminalCommands.install)
terminal_app.command("uninstall")(TerminalCommands.uninstall)
terminal_app.command("enable", hidden=True, deprecated=True)(TerminalCommands.install)
terminal_app.command("disable", hidden=True, deprecated=True)(
    TerminalCommands.uninstall
)
terminal_app.command("restart")(TerminalCommands.restart)
terminal_app.command("status")(TerminalCommands.status)
