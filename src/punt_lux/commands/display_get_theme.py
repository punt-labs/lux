"""``display get-theme`` -- return the active theme and the switchable set."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Self, final

from punt_lux.commands._faults import render_fault
from punt_lux.commands._result import CommandResult
from punt_lux.operations import OpError, ThemeState

if TYPE_CHECKING:
    from punt_lux.commands._ports import Ctx, ThemeOps


@final
class DisplayGetThemeCommand:
    """Return the display's active theme and the themes it can switch to."""

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    async def execute(self, ctx: Ctx[ThemeOps]) -> ThemeState | OpError:
        """Return the typed theme state, or the display's fault."""
        return await asyncio.to_thread(ctx.ops.get_theme)

    async def __call__(self, ctx: Ctx[ThemeOps]) -> CommandResult:
        """Run :meth:`execute` and render its outcome into the shared envelope."""
        result = await self.execute(ctx)
        if isinstance(result, OpError):
            return render_fault(result)
        return CommandResult(
            text=f"theme:{result.theme}",
            json_data=result.model_dump(mode="json"),
        )


display_get_theme: DisplayGetThemeCommand = DisplayGetThemeCommand()
