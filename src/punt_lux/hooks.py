"""Pure handler functions for Claude Code lifecycle hooks.

Called by the CLI dispatcher (``lux hook <event>``), never directly.
Each handler takes structured input and returns structured output.
"""

from __future__ import annotations

import json
import sys

from punt_lux.config import ConfigManager

# What a session is told at start when the display is on. The Beads entry it owns
# is no longer anything the agent does: this session's applet registers it on
# connect and services the click itself. Saying so is still worth the line,
# because it tells the agent what NOT to do — a callback it registered over MCP
# would be refused (an MCP connection holds no listen leg), and a poll for clicks
# would find nothing and add latency to a path that has none.
_DISPLAY_ON_CONTEXT = (
    "Lux display mode: on. Visual output will be rendered when appropriate. "
    "This session's own applets own their entries in the Lux menu bar and "
    "service their clicks directly, in milliseconds and without a turn of "
    "yours — so do not register menu callbacks and do not poll for clicks. "
    "When the user asks for the beads board, build it with the /lux:beads skill."
)


def handle_session_start() -> dict[str, object]:
    """SessionStart — read display mode and return context.

    When the display is on, the context also says who owns this session's menu
    entries — its own server process, not the agent — so the agent does not
    duplicate work that is already done and would now be refused.
    """
    cfg = ConfigManager().read()

    if cfg.display == "y":
        msg = _DISPLAY_ON_CONTEXT
    else:
        msg = "Lux display mode: off. Visual output disabled."

    return {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": msg,
        }
    }


def emit(output: dict[str, object]) -> None:
    """Write JSON response to stdout."""
    sys.stdout.write(json.dumps(output) + "\n")
