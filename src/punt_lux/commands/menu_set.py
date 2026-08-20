"""``menu set`` -- replace the Hub-owned menu bar and render the shared envelope.

Text shapes match the shipped ``set_menu`` MCP tool byte-for-byte -- ``"ok"``
on success, the shared fault line on error.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.commands._faults import render_fault
from punt_lux.commands._result import CommandResult
from punt_lux.operations import Ok, OpError

if TYPE_CHECKING:
    from punt_lux.commands._ports import Ctx, MenuOps
    from punt_lux.operations import SetMenuRequest


@final
class MenuSetCommand:
    """Replace the Hub-owned menu bar; the replicator pushes the change."""

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    async def execute(
        self, ctx: Ctx[MenuOps], request: SetMenuRequest | OpError
    ) -> Ok | OpError:
        """Install ``request`` as the new menu bar and return the typed outcome."""
        return ctx.ops.set_menu(request)

    async def __call__(
        self, ctx: Ctx[MenuOps], request: SetMenuRequest | OpError
    ) -> CommandResult:
        """Run :meth:`execute` and render its outcome into the shared envelope."""
        result = await self.execute(ctx, request)
        if isinstance(result, OpError):
            return render_fault(result)
        return CommandResult(text="ok")


menu_set: MenuSetCommand = MenuSetCommand()
