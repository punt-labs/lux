"""``frame close`` -- tear down a frame's scenes and disarm its TTL."""

from __future__ import annotations

import asyncio
from typing import Self, final

from punt_lux.commands._faults import render_fault
from punt_lux.commands._frame_close_request import FrameCloseRequest
from punt_lux.commands._result import CommandResult
from punt_lux.operations import Ok, OpError


@final
class FrameCloseCommand:
    """Close a frame: remove its scenes on the Hub and repaint them blank."""

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    async def execute(self, request: FrameCloseRequest) -> Ok | OpError:
        """Close the requested frame and return the typed outcome."""
        return await asyncio.to_thread(request.ctx.ops.close_frame, request.target)

    async def __call__(self, request: FrameCloseRequest) -> CommandResult:
        """Run :meth:`execute` and render its outcome into the shared envelope."""
        result = await self.execute(request)
        if isinstance(result, OpError):
            return render_fault(result)
        return CommandResult(text=f"closed:{request.frame_id}")


frame_close: FrameCloseCommand = FrameCloseCommand()
