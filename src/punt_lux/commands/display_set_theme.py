"""``display set-theme`` -- switch the display theme and return the new state."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Self, final

from punt_lux.commands._faults import render_fault
from punt_lux.commands._result import CommandResult
from punt_lux.operations import OpError, ThemeState

if TYPE_CHECKING:
    from punt_lux.commands._ports import Ctx, ThemeOps
    from punt_lux.operations import SetThemeRequest


@final
class DisplaySetThemeCommand:
    """Switch the display theme and return the new theme state."""

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    async def execute(
        self, ctx: Ctx[ThemeOps], request: SetThemeRequest | OpError
    ) -> ThemeState | OpError:
        """Switch to ``request.theme`` and return the new state, or the fault."""
        return await asyncio.to_thread(ctx.ops.set_theme, request)

    async def __call__(
        self, ctx: Ctx[ThemeOps], request: SetThemeRequest | OpError
    ) -> CommandResult:
        """Run :meth:`execute` and render its outcome into the shared envelope."""
        result = await self.execute(ctx, request)
        if isinstance(result, OpError):
            return render_fault(result)
        return CommandResult(
            text=f"theme:{result.theme}",
            json_data=result.model_dump(mode="json"),
        )


display_set_theme: DisplaySetThemeCommand = DisplaySetThemeCommand()
