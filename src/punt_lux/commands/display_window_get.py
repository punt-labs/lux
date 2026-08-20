"""``display window-get`` -- return the window's opacity/font/decoration/idle FPS."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Self, final

from punt_lux.commands._faults import render_fault
from punt_lux.commands._result import CommandResult
from punt_lux.operations import OpError, WindowSettings

if TYPE_CHECKING:
    from punt_lux.commands._ports import Ctx, WindowOps


@final
class DisplayWindowGetCommand:
    """Return the window's opacity, font scale, decoration, and idle rate."""

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    async def execute(self, ctx: Ctx[WindowOps]) -> WindowSettings | OpError:
        """Return the typed window settings, or the display's fault."""
        return await asyncio.to_thread(ctx.ops.get_window_settings)

    async def __call__(self, ctx: Ctx[WindowOps]) -> CommandResult:
        """Run :meth:`execute` and render its outcome into the shared envelope."""
        result = await self.execute(ctx)
        if isinstance(result, OpError):
            return render_fault(result)
        return CommandResult(text="window:ok", json_data=result.model_dump(mode="json"))


display_window_get: DisplayWindowGetCommand = DisplayWindowGetCommand()
