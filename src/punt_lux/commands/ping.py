"""``ping`` -- round-trip a display ping and render the shared result envelope.

Text shapes match the shipped MCP tool byte-for-byte -- ``"pong rtt=X.XXXs"``,
``"not running"``, ``"timeout"``, and ``"error: <reason>"`` -- so adapters that
already print those lines pick up the command without changing output.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, cast, final

from punt_lux.commands._result import CommandResult
from punt_lux.operations import OpError, Pong

if TYPE_CHECKING:
    from punt_lux.commands._result import Ctx
    from punt_lux.operations.models.common import OpErrorCode


@final
class PingCommand:
    """Round-trip a display ping and render the shared result envelope."""

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    async def __call__(self, ctx: Ctx, wait: float | None = None) -> CommandResult:
        """Round-trip ``ctx.ops.ping(wait)`` and render its outcome."""
        result = ctx.ops.ping(wait)
        if isinstance(result, OpError):
            return self._render_error(result)
        return CommandResult(
            text=f"pong rtt={result.rtt_seconds:.3f}s",
            json_data={"rtt_seconds": result.rtt_seconds},
        )

    @staticmethod
    def to_operation(result: CommandResult) -> Pong | OpError:
        """Reconstruct the typed operation result from *result*'s envelope.

        Raises ``ValueError`` if *result* did not come from :class:`PingCommand`
        -- every outcome ``__call__`` produces sets ``json_data``, so a missing
        envelope means the caller passed a result this command never built.
        """
        data = result.json_data
        if data is None:
            msg = "CommandResult has no json_data; not a PingCommand result"
            raise ValueError(msg)
        if result.error:
            return OpError(
                code=cast("OpErrorCode", data["code"]),
                reason=str(data["reason"]),
            )
        return Pong(rtt_seconds=cast("float", data["rtt_seconds"]))

    @staticmethod
    def _render_error(err: OpError) -> CommandResult:
        """Render an ``OpError`` into the CommandResult with the shipped text line."""
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
