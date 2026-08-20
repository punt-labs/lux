"""Turn a :class:`CommandResult` into an MCP tool's string return or a raise.

Every MCP tool that returns a string envelope must raise ``ToolError`` when the
command signalled a failure -- returning the error line as if it were a success
looks like a normal tool result to the MCP client. This helper is the single
place that discipline lives so a new tool cannot silently regress.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from fastmcp.exceptions import ToolError

if TYPE_CHECKING:
    from punt_lux.commands import CommandResult

__all__ = ["Signal", "signal"]


@final
class Signal:
    """Route a :class:`CommandResult` to an MCP tool's return or a raise."""

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    def __call__(self, result: CommandResult) -> str:
        """Return ``result.text`` on success; raise :class:`ToolError` on failure."""
        if result.error:
            raise ToolError(result.text)
        return result.text


signal: Signal = Signal()
