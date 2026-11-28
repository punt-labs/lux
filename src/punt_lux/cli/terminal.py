"""Machine-local opt-in terminal daemon: install, uninstall, status and restart."""

from __future__ import annotations

from collections.abc import Callable

import typer

from punt_lux.service.terminal_service import TerminalService

terminal_app = typer.Typer(help="Manage this machine's Terminal launcher.")


class TerminalCommands:
    @staticmethod
    def _action(operation: Callable[[], str]) -> None:
        try:
            typer.echo(operation())
        except RuntimeError as error:
            typer.echo(str(error), err=True)
            raise typer.Exit(1) from error

    @staticmethod
    @terminal_app.command("enable", hidden=True, deprecated=True)
    @terminal_app.command()
    def install() -> None:
        """Enable on this machine: install/start the supervised owner and launcher."""
        TerminalCommands._action(TerminalService().enable)

    @staticmethod
    @terminal_app.command("disable", hidden=True, deprecated=True)
    @terminal_app.command()
    def uninstall() -> None:
        """Disable here: stops held programs and removes supervisor registration."""
        TerminalCommands._action(TerminalService().disable)

    @staticmethod
    @terminal_app.command()
    def restart() -> None:
        """Explicitly restart the owner; this ends its held programs."""
        TerminalCommands._action(TerminalService().restart)

    @staticmethod
    @terminal_app.command()
    def status() -> None:
        """Read this machine's supervisor state without starting anything."""
        typer.echo(f"luxd-pty {'' if TerminalService().is_active else 'not '}running")
