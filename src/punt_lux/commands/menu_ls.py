"""``menu ls`` -- return the Hub-authoritative menu bar."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Self, final

from punt_lux.commands._faults import render_error
from punt_lux.commands._result import CommandResult
from punt_lux.operations import OpError

if TYPE_CHECKING:
    from punt_lux.commands._ports import Ctx, MenuOps
    from punt_lux.operations import MenuList


@final
class MenuLsCommand:
    """Return the Hub-owned menu bar and its callback submenus."""

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    async def execute(self, ctx: Ctx[MenuOps]) -> MenuList | OpError:
        """Return the whole Hub-authoritative menu state, or an ``OpError``."""
        return await asyncio.to_thread(ctx.ops.list_menus)

    async def __call__(self, ctx: Ctx[MenuOps]) -> CommandResult:
        """Run :meth:`execute` and render its outcome into the shared envelope."""
        result = await self.execute(ctx)
        if isinstance(result, OpError):
            return render_error(result)
        return CommandResult(
            text=f"menus:{len(result.menus)}",
            json_data=result.model_dump(mode="json"),
        )


menu_ls: MenuLsCommand = MenuLsCommand()
