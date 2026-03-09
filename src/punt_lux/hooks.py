"""Pure handler functions for Claude Code lifecycle hooks.

Called by the CLI dispatcher (``lux hook <event>``), never directly.
Each handler takes structured input and returns structured output.
"""

from __future__ import annotations

import json
import sys
from typing import Any

from punt_lux.config import read_config, resolve_config_path


def handle_session_start(_data: dict[str, Any]) -> dict[str, Any]:
    """SessionStart — read display mode and return context."""
    cfg = read_config(resolve_config_path())

    if cfg.display == "y":
        msg = "Lux display mode: on. Visual output will be rendered when appropriate."
    else:
        msg = "Lux display mode: off. Visual output disabled."

    return {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": msg,
        }
    }


def emit(output: dict[str, Any]) -> None:
    """Write JSON response to stdout."""
    sys.stdout.write(json.dumps(output) + "\n")
