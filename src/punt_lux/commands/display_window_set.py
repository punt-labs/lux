"""``display window-set`` -- change window settings and return the new state."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Self, final

from punt_lux.commands._faults import render_fault
from punt_lux.commands._result import CommandResult
from punt_lux.operations import OpError, WindowSettings

if TYPE_CHECKING:
    from punt_lux.commands._ports import Ctx, WindowOps
    from punt_lux.operations import WindowSettingsPatch


@final
class DisplayWindowSetCommand:
    """Change the provided window settings and return the new settings."""

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    async def execute(
        self, ctx: Ctx[WindowOps], patch: WindowSettingsPatch | OpError
    ) -> WindowSettings | OpError:
        """Apply ``patch`` and return the new settings, or the display's fault."""
        return await asyncio.to_thread(ctx.ops.set_window_settings, patch)

    async def __call__(
        self, ctx: Ctx[WindowOps], patch: WindowSettingsPatch | OpError
    ) -> CommandResult:
        """Run :meth:`execute` and render its outcome into the shared envelope."""
        result = await self.execute(ctx, patch)
        if isinstance(result, OpError):
            return render_fault(result)
        return CommandResult(text="window:ok", json_data=result.model_dump(mode="json"))


display_window_set: DisplayWindowSetCommand = DisplayWindowSetCommand()
