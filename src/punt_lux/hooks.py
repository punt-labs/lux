"""Pure handler functions for Claude Code lifecycle hooks.

Called by the CLI dispatcher (``lux hook <event>``), never directly.
Each handler takes structured input and returns structured output.
"""

from __future__ import annotations

import json
import os
import re
import select
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

from punt_lux.config import read_config, resolve_config_path

# bd mutation commands that should trigger a beads board refresh
_BD_MUTATION_RE = re.compile(
    r"(?:^|[;&|\s])bd\s+(create|close|update|dep|sync)(?:\s|$)",
)


def handle_session_start() -> dict[str, object]:
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


def read_hook_input() -> dict[str, object]:
    """Read JSON hook payload from stdin (non-blocking).

    Uses select + os.read to avoid blocking forever when
    Claude Code does not close the stdin pipe.  See DES-027.
    """
    try:
        fd = sys.stdin.fileno()
        if not select.select([fd], [], [], 0.1)[0]:
            return {}
        chunks: list[bytes] = []
        while True:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            chunks.append(chunk)
            if not select.select([fd], [], [], 0.05)[0]:
                break
        raw = b"".join(chunks).decode()
        if not raw.strip():
            return {}
        parsed: object = json.loads(raw)
        if isinstance(parsed, dict):
            return cast("dict[str, object]", parsed)
        return {}
    except (json.JSONDecodeError, OSError, ValueError):
        return {}


def handle_post_bash(data: dict[str, object]) -> None:
    """PostToolUse Bash — refresh beads board after bd mutations.

    Side-effect only handler — fires ``lux show beads`` in a subprocess
    and returns immediately.  No context injection.
    """
    command = ""
    tool_input = data.get("tool_input")
    if isinstance(tool_input, dict):
        inner = cast("dict[str, Any]", tool_input)
        cmd_val = inner.get("command")
        if isinstance(cmd_val, str):
            command = cmd_val

    if not _BD_MUTATION_RE.search(command):
        return

    # Gate: .beads/ must exist in the repo
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return
        repo_root = Path(result.stdout.strip())
    except OSError:
        return

    if not (repo_root / ".beads").is_dir():
        return

    # Fire-and-forget: refresh the display
    subprocess.Popen(
        ["lux", "show", "beads"],
        cwd=str(repo_root),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def emit(output: dict[str, object]) -> None:
    """Write JSON response to stdout."""
    sys.stdout.write(json.dumps(output) + "\n")
