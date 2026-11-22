"""Controlled parent-side applet launch diagnostics."""

from __future__ import annotations

import logging
from enum import StrEnum
from typing import final

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
class AppletRecords:
    """Persist launch outcomes with severity and actual child correlation."""

    __slots__ = ()

    @staticmethod
    def record(event: AppletEvent, child_pid: int) -> None:
        """Record only controlled reasons and an existing child process number."""
        messages = {
            AppletEvent.INTENT: "SessionStart applet launch intent: spawning",
            AppletEvent.LAUNCHED: "SessionStart applet launched: spawned",
            AppletEvent.MISSING: "SessionStart applet skipped: executable missing",
            AppletEvent.RUNNING: "SessionStart applet skipped: already running",
            AppletEvent.PROBE_ERROR: "SessionStart applet failed: process probe error",
            AppletEvent.SPAWN_ERROR: "SessionStart applet failed: spawn error",
        }
        level = (
            logging.WARNING
            if event in (AppletEvent.PROBE_ERROR, AppletEvent.SPAWN_ERROR)
            else logging.INFO
        )
        suffix = (
            f" (child pid={child_pid})"
            if child_pid > 0
            and event in (AppletEvent.LAUNCHED, AppletEvent.SPAWN_ERROR)
            else ""
        )
        logger.log(level, "%s%s", messages[event], suffix)
