"""``event ls`` -- return the display's recent interaction events, proxied."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Self, final

from punt_lux.commands._faults import render_fault
from punt_lux.commands._result import CommandResult
from punt_lux.operations import OpError

if TYPE_CHECKING:
    from punt_lux.commands._ports import Ctx, EventOps
    from punt_lux.operations.models.query_events import RecentEvents


@final
class EventLsCommand:
    """Return the display's recent interactions over luxd's one connection."""

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    async def execute(self, ctx: Ctx[EventOps], count: int) -> RecentEvents | OpError:
        """Return the last ``count`` events, or the display's fault."""
        return await asyncio.to_thread(ctx.ops.list_recent_events, count)

    async def __call__(self, ctx: Ctx[EventOps], count: int) -> CommandResult:
        """Run :meth:`execute` and render its outcome into the shared envelope."""
        result = await self.execute(ctx, count)
        if isinstance(result, OpError):
            return render_fault(result)
        return CommandResult(
            text=f"events:{len(result.events)}",
            json_data=result.model_dump(mode="json"),
        )


event_ls: EventLsCommand = EventLsCommand()
