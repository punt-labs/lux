"""``frame set-state`` -- change a frame's minimize state through the shared envelope.

The shipped ``set_frame_state`` MCP tool and REST route both return the typed
``Ok | OpError``; this command adds the CLI text envelope for the CLI adapter
to render (``"ok"`` on success, the shared fault line on error).
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Self, final

from punt_lux.commands._faults import render_fault
from punt_lux.commands._result import CommandResult
from punt_lux.operations import Ok, OpError

if TYPE_CHECKING:
    from punt_lux.commands._ports import Ctx, FrameOps
    from punt_lux.operations import FrameStatePatch


@final
class FrameSetStateCommand:
    """Change a frame's minimize state."""

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    async def execute(
        self,
        ctx: Ctx[FrameOps],
        frame_id: str,
        patch: FrameStatePatch | OpError,
    ) -> Ok | OpError:
        """Apply ``patch`` to ``frame_id`` and return the typed outcome."""
        return await asyncio.to_thread(ctx.ops.set_frame_state, frame_id, patch)

    async def __call__(
        self,
        ctx: Ctx[FrameOps],
        frame_id: str,
        patch: FrameStatePatch | OpError,
    ) -> CommandResult:
        """Run :meth:`execute` and render its outcome into the shared envelope."""
        result = await self.execute(ctx, frame_id, patch)
        if isinstance(result, OpError):
            return render_fault(result)
        return CommandResult(text="ok")


frame_set_state: FrameSetStateCommand = FrameSetStateCommand()
