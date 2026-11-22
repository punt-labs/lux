"""Installed Claude Code hook command registration and diagnostics boundary."""

from __future__ import annotations

from typing import final

import typer

from punt_lux.hooks import emit, handle_session_start
from punt_lux.logging_config import configure_logging
from punt_lux.session_start import AppletEvent, SessionStartDecisions


@final
class HookCommands:
    """Register the context dispatcher and the shell hook's safe event sink."""

    __slots__ = ()

    @classmethod
    def register(cls, app: typer.Typer) -> None:
        """Attach the internal commands to the CLI's hook group."""
        app.command("applet-event")(cls.applet_event)

    @staticmethod
    def session_start() -> None:
        """Return display context without waiting for hook stdin to close."""
        configure_logging("lux", "hook")
        emit(handle_session_start())

    @staticmethod
    def applet_event(
        event: AppletEvent, child_pid: int = typer.Option(0, min=0)
    ) -> None:
        """Persist a controlled launch event even with standard streams discarded."""
        configure_logging("lux", "hook")
        SessionStartDecisions.record(event, child_pid)
