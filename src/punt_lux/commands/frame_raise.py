"""``frame raise`` -- bring a frame to the front, restoring it if minimized."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Self, final

from punt_lux.commands._faults import render_fault
from punt_lux.commands._result import CommandResult
from punt_lux.operations import FrameRaise, FrameRef, OpError

if TYPE_CHECKING:
    from punt_lux.commands._ports import Ctx, FrameOps


@final
class FrameRaiseCommand:
    """Bring a frame to the front, restoring it if minimized."""

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    async def execute(self, ctx: Ctx[FrameOps], ref: FrameRef) -> FrameRaise | OpError:
        """Raise the frame ``ref`` names and return the outcome."""
        return await asyncio.to_thread(ctx.ops.raise_frame, ref)

    async def __call__(self, ctx: Ctx[FrameOps], ref: FrameRef) -> CommandResult:
        """Run :meth:`execute` and render its outcome into the shared envelope."""
        result = await self.execute(ctx, ref)
        if isinstance(result, OpError):
            return render_fault(result)
        return CommandResult(
            text=f"raised:{result.raised}", json_data=result.model_dump(mode="json")
        )


frame_raise: FrameRaiseCommand = FrameRaiseCommand()
