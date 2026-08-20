"""The shared proxied-operation fault line every command's fault-only path renders.

Several commands proxy a single call to the display or the Hub and, on success,
render a fixed text with no data of its own (``"cleared"``, ``"ok"``,
``registered:<id>``): the only outcome worth rendering differently is the
fault. This is a standalone utility, not a method of any one command's class
(PY-OO-7) -- it has no state and no vocabulary in common with any single
command, only with the ``OpError`` every one of them may receive.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from punt_lux.commands._result import CommandResult

if TYPE_CHECKING:
    from punt_lux.operations import OpError

__all__ = ["render_fault"]


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
