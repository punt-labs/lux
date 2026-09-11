"""``frame remove`` -- tear down a frame's scenes and disarm its TTL."""

from __future__ import annotations

import asyncio
from typing import Self, final

from punt_lux.commands._faults import render_fault
from punt_lux.commands._frame_remove_request import FrameRemoveRequest
from punt_lux.commands._result import CommandResult
from punt_lux.operations import Ok, OpError


@final
class FrameRemoveCommand:
    """Remove a frame's content: tear down its scenes on the Hub and repaint blank."""

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    async def execute(self, request: FrameRemoveRequest) -> Ok | OpError:
        """Remove the requested frame's content and return the typed outcome."""
        ops, frame_id, scope = request.ctx.ops, request.frame_id, request.scope
        return await asyncio.to_thread(ops.remove_frame, frame_id, scope=scope)

    async def __call__(self, request: FrameRemoveRequest) -> CommandResult:
        """Run :meth:`execute` and render its outcome into the shared envelope."""
        result = await self.execute(request)
        if isinstance(result, OpError):
            return render_fault(result)
        return CommandResult(text=f"removed:{request.frame_id}")


frame_remove: FrameRemoveCommand = FrameRemoveCommand()
