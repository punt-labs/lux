"""``display info`` -- return the display's backend, geometry, frame rate, identity."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Self, final

from punt_lux.commands._faults import render_fault
from punt_lux.commands._result import CommandResult
from punt_lux.operations import DisplayInfo, OpError

if TYPE_CHECKING:
    from punt_lux.commands._ports import Ctx, DisplayInfoOps


@final
class DisplayInfoCommand:
    """Return the display's backend, geometry, frame rate, and identity."""

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    async def execute(self, ctx: Ctx[DisplayInfoOps]) -> DisplayInfo | OpError:
        """Return the display's typed info record, or the display's fault."""
        return await asyncio.to_thread(ctx.ops.get_display_info)

    async def __call__(self, ctx: Ctx[DisplayInfoOps]) -> CommandResult:
        """Run :meth:`execute` and render its outcome into the shared envelope."""
        result = await self.execute(ctx)
        if isinstance(result, OpError):
            return render_fault(result)
        return CommandResult(
            text=f"display:{result.backend}",
            json_data=result.model_dump(mode="json"),
        )


display_info: DisplayInfoCommand = DisplayInfoCommand()
