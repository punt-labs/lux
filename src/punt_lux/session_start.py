"""Safe SessionStart decisions shared by the installed hook entry points."""

from __future__ import annotations

import logging
from enum import StrEnum
from typing import final

from punt_lux.config import ConfigManager

logger = logging.getLogger(__name__)


class AppletEvent(StrEnum):
    """The fixed, non-sensitive vocabulary accepted from the shell hook."""

    INTENT = "intent"
    LAUNCHED = "launched"
    MISSING = "missing"
    RUNNING = "already-running"
    PROBE_ERROR = "probe-error"
    SPAWN_ERROR = "spawn-error"


@final
class SessionStartDecisions:
    """Record launch events and decide the display context without private data."""

    __slots__ = ()

    @staticmethod
    def record(event: AppletEvent, child_pid: int) -> None:
        """Record only controlled reasons and an optional child process number."""
        messages = {
            AppletEvent.INTENT: "SessionStart applet launch intent: spawning",
            AppletEvent.LAUNCHED: "SessionStart applet launched: spawned",
            AppletEvent.MISSING: "SessionStart applet skipped: executable missing",
            AppletEvent.RUNNING: "SessionStart applet skipped: already running",
            AppletEvent.PROBE_ERROR: "SessionStart applet failed: process probe error",
            AppletEvent.SPAWN_ERROR: "SessionStart applet failed: spawn error",
        }
        logger.info("%s (child pid=%d)", messages[event], child_pid)

    @staticmethod
    def display_context(enabled_context: str) -> str:
        """Read display mode and log a safe decision even if configuration fails."""
        try:
            enabled = ConfigManager().read().display == "y"
        except Exception as error:
            logger.error(
                "SessionStart display decision failed: %s", type(error).__name__
            )
            raise
        logger.info(
            "SessionStart display decision: %s", "enabled" if enabled else "disabled"
        )
        return (
            enabled_context
            if enabled
            else "Lux display mode: off. Visual output disabled."
        )
