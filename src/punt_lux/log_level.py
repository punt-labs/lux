"""The one knob that lowers a process's logging floor.

Each of lux's entry points picks the floor its stream can afford — a session
applet's stderr belongs to whoever started it, the display writes to a file of
its own — and this reads the override. A process inheriting no value keeps its
own floor, so nothing may set ``LUX_LOG_LEVEL`` on a child's behalf.
"""

from __future__ import annotations

import logging
import os
import sys

__all__ = ["level_from_env"]

_LOG_LEVELS: dict[str, int] = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}


def level_from_env(default: str) -> int:
    """Read ``LUX_LOG_LEVEL``, falling back to ``default`` and saying so if unusable.

    An unusable value is reported and ignored rather than fatal: a mistyped
    environment variable must not stop a session's applet from starting.
    """
    raw = os.environ.get("LUX_LOG_LEVEL", default).upper()
    level = _LOG_LEVELS.get(raw)
    if level is None:
        # Written to the stream rather than logged: this runs to decide how
        # logging is configured, so there is no logger to say it through yet.
        sys.stderr.write(
            f"WARNING: LUX_LOG_LEVEL={raw!r} is not valid, defaulting to {default}\n"
        )
        return _LOG_LEVELS[default]
    return level
