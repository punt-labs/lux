"""Shared ``OpError`` renderers for commands that echo the shipped error line.

Two renderers, chosen by the family's vocabulary:

- :func:`render_fault` -- the display-proxy vocabulary (``"not running"``,
  ``"timeout"``, ``"error: <reason>"``). Ping, frame-state, menu-set: every
  command whose ``OpError`` may name a display-side fault.
- :func:`render_error` -- the generic non-display fallback
  (``"error: <prefix><reason>"``). Scene rejection, session identify, callback
  register: every command whose failure vocabulary has no display-fault codes.

Both are module-level utilities (PY-OO-7 legitimate exception -- pure
functions with no shared vocabulary with any one command, only with
``OpError`` every command may receive).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from punt_lux.commands._result import CommandResult

if TYPE_CHECKING:
    from punt_lux.operations import OpError

__all__ = ["render_error", "render_fault"]


def render_fault(err: OpError) -> CommandResult:
    """Render a proxied operation's ``OpError`` as its legacy fault line.

    A display that is not running reads ``"not running"`` and a bounded
    round-trip that elapsed reads ``"timeout"``, matching the two
    short-circuits the display tools have always returned; every other cause
    reads ``"error: <reason>"``.
    """
    if err.code == "display_unavailable":
        text = "not running"
    elif err.code == "timeout":
        text = "timeout"
    else:
        text = f"error: {err.reason}"
    return CommandResult(
        text=text,
        json_data={"code": err.code, "reason": err.reason},
        error=True,
        exit_code=1,
    )


def render_error(err: OpError, prefix: str = "") -> CommandResult:
    """Render a non-display ``OpError`` as ``"error: <prefix><reason>"``.

    ``prefix`` covers the shipped ``"scene not updated -- "`` /
    ``"scene not rendered -- "`` shapes; call without it for a bare
    ``"error: <reason>"`` line. Never specialises a code -- use
    :func:`render_fault` for the display's own fault vocabulary.
    """
    return CommandResult(
        text=f"error: {prefix}{err.reason}",
        json_data={"code": err.code, "reason": err.reason},
        error=True,
        exit_code=1,
    )
