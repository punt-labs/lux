"""Round-trip a display ping and render the result as text or JSON."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Self, final

from punt_lux.commands._faults import render_fault
from punt_lux.commands._result import CommandResult
from punt_lux.operations import OpError

if TYPE_CHECKING:
    from punt_lux.commands._ports import Ctx, PingOps
    from punt_lux.operations import Pong


@final
class PingCommand:
    """Round-trip a display ping and render the shared result envelope."""

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    async def execute(
        self, ctx: Ctx[PingOps], wait: float | None = None
    ) -> Pong | OpError:
        """Round-trip ``ctx.ops.ping(wait)`` off the event loop and return it.

        REST calls this directly, skipping the rendered envelope; threaded
        because ``ctx.ops.ping`` blocks on display-socket I/O.
        """
        return await asyncio.to_thread(ctx.ops.ping, wait)

    async def __call__(
        self, ctx: Ctx[PingOps], wait: float | None = None
    ) -> CommandResult:
        """Run :meth:`execute` and render its outcome into the shared envelope."""
        result = await self.execute(ctx, wait)
        if isinstance(result, OpError):
            return render_fault(result)
        return CommandResult(
            text=f"pong rtt={result.rtt_seconds:.3f}s",
            json_data={"rtt_seconds": result.rtt_seconds},
        )


ping: PingCommand = PingCommand()
"""Run a display ping with a command context; apps should use LuxClient.ping."""
