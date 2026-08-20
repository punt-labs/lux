"""``error ls`` -- return the display's recent errors, proxied."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Self, final

from punt_lux.commands._faults import render_fault
from punt_lux.commands._result import CommandResult
from punt_lux.operations import OpError

if TYPE_CHECKING:
    from punt_lux.commands._ports import Ctx, ErrorOps
    from punt_lux.operations.models.query_errors import RecentErrors


@final
class ErrorLsCommand:
    """Return the display's recent errors over luxd's one connection."""

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    async def execute(self, ctx: Ctx[ErrorOps], count: int) -> RecentErrors | OpError:
        """Return the last ``count`` errors, or the display's fault."""
        return await asyncio.to_thread(ctx.ops.list_errors, count)

    async def __call__(self, ctx: Ctx[ErrorOps], count: int) -> CommandResult:
        """Run :meth:`execute` and render its outcome into the shared envelope."""
        result = await self.execute(ctx, count)
        if isinstance(result, OpError):
            return render_fault(result)
        return CommandResult(
            text=f"errors:{len(result.errors)}",
            json_data=result.model_dump(mode="json"),
        )


error_ls: ErrorLsCommand = ErrorLsCommand()
