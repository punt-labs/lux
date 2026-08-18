"""``ping`` -- round-trip a display ping and render the result envelope.

The command is a callable object (:class:`PingCommand`) so the four adapters
share one instance and the ratchet counts the class-per-command shape the rest
of the layer uses (vox reference: ``VoiceCommand``).

Text shapes are chosen so the shipped MCP tool output stays byte-identical --
``"pong rtt=0.042s"`` on success, ``"not running"`` when the display is down,
``"timeout"`` when the round-trip elapsed. Any other engine error reads
``"error: <reason>"``. The ``json_data`` envelope is the structured form the
CLI's ``--json`` mode and the REST route consume.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.commands._result import CommandResult
from punt_lux.operations import OpError

if TYPE_CHECKING:
    from punt_lux.commands._result import Ctx


@final
class PingCommand:
    """Round-trip a display ping and render the shared result envelope."""

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    async def __call__(self, ctx: Ctx, wait: float | None = None) -> CommandResult:
        """Round-trip ``ctx.ops.ping(wait)`` and render its outcome.

        Success renders ``pong rtt={seconds:.3f}s`` (matching the shipped MCP
        surface) with a ``{"rtt_seconds": float}`` envelope. Every error path
        renders through :meth:`_render_error` so a display that is not running
        reads ``"not running"``, a bounded round-trip that elapsed reads
        ``"timeout"``, and anything else reads ``"error: <reason>"`` -- the
        three status lines the MCP surface has always emitted.
        """
        result = ctx.ops.ping(wait)
        if isinstance(result, OpError):
            return self._render_error(result)
        return CommandResult(
            text=f"pong rtt={result.rtt_seconds:.3f}s",
            json_data={"rtt_seconds": result.rtt_seconds},
        )

    @staticmethod
    def _render_error(err: OpError) -> CommandResult:
        """Render an ``OpError`` into a CommandResult with the shipped text lines.

        The three-way split (down / timeout / other) is the shipped MCP shape
        pulled through the command layer so every adapter picks it up in one
        place instead of copying the mapping three times.
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


ping: PingCommand = PingCommand()
