"""``menu ls`` -- return the Hub-authoritative menu bar."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.commands._result import CommandResult

if TYPE_CHECKING:
    from punt_lux.commands._ports import Ctx, MenuOps
    from punt_lux.operations import MenuList


@final
class MenuLsCommand:
    """Return the Hub-owned menu bar and its callback submenus."""

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    async def execute(self, ctx: Ctx[MenuOps]) -> MenuList:
        """Return the whole Hub-authoritative menu state."""
        return ctx.ops.list_menus()

    async def __call__(self, ctx: Ctx[MenuOps]) -> CommandResult:
        """Run :meth:`execute` and render its outcome into the shared envelope."""
        result = await self.execute(ctx)
        return CommandResult(
            text=f"menus:{len(result.menus)}",
            json_data=result.model_dump(mode="json"),
        )


menu_ls: MenuLsCommand = MenuLsCommand()
