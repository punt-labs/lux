"""``frame close`` -- tear down a frame's scenes and disarm its TTL."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Self, final

from punt_lux.commands._faults import render_fault
from punt_lux.commands._result import CommandResult
from punt_lux.operations import Ok, OpError

if TYPE_CHECKING:
    from punt_lux.commands._ports import Ctx, FrameOps


@final
class FrameCloseCommand:
    """Close a frame: remove its scenes on the Hub and repaint them blank."""

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    async def execute(self, ctx: Ctx[FrameOps], frame_id: str) -> Ok | OpError:
        """Close ``frame_id`` and return the typed outcome."""
        return await asyncio.to_thread(ctx.ops.close_frame, frame_id)

    async def __call__(self, ctx: Ctx[FrameOps], frame_id: str) -> CommandResult:
        """Run :meth:`execute` and render its outcome into the shared envelope."""
        result = await self.execute(ctx, frame_id)
        if isinstance(result, OpError):
            return render_fault(result)
        return CommandResult(text=f"closed:{frame_id}")


frame_close: FrameCloseCommand = FrameCloseCommand()
