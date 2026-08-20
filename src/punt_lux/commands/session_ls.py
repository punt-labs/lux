"""``session ls`` -- list the Hub's sessions and their scopes."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Self, final

from punt_lux.commands._faults import render_error
from punt_lux.commands._result import CommandResult
from punt_lux.operations import OpError

if TYPE_CHECKING:
    from punt_lux.commands._ports import Ctx, SessionOps
    from punt_lux.operations import ClientList


@final
class SessionLsCommand:
    """List the Hub's live sessions with their declared identities."""

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    async def execute(self, ctx: Ctx[SessionOps]) -> ClientList | OpError:
        """Return every Hub session, or an ``OpError`` on transport fault."""
        return await asyncio.to_thread(ctx.ops.list_clients)

    async def __call__(self, ctx: Ctx[SessionOps]) -> CommandResult:
        """Run :meth:`execute` and render its outcome into the shared envelope."""
        result = await self.execute(ctx)
        if isinstance(result, OpError):
            return render_error(result)
        return CommandResult(
            text=f"sessions:{len(result.clients)}",
            json_data=result.model_dump(mode="json"),
        )


session_ls: SessionLsCommand = SessionLsCommand()
