"""``display state-get`` -- return the Display's own widget/frame state."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Self, final

from punt_lux.commands._faults import render_fault
from punt_lux.commands._result import CommandResult
from punt_lux.wire.operations import OpError

if TYPE_CHECKING:
    from punt_lux.wire.operations import DisplayStateSnapshot, Scope
    from punt_lux.wire.ops import Ctx
    from punt_lux.wire.ops.display_state import DisplayStateOps

__all__ = ["display_state_get"]


@final
class DisplayStateGetCommand:
    """Return the caller's own widget/frame state, proxied over one connection."""

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    async def execute(
        self, ctx: Ctx[DisplayStateOps], *, scope: Scope
    ) -> DisplayStateSnapshot | OpError:
        """Return the typed snapshot, or the display's fault."""
        return await asyncio.to_thread(ctx.ops.get_display_state, scope=scope)

    async def __call__(
        self, ctx: Ctx[DisplayStateOps], *, scope: Scope
    ) -> CommandResult:
        """Run :meth:`execute` and render its outcome into the shared envelope."""
        result = await self.execute(ctx, scope=scope)
        if isinstance(result, OpError):
            return render_fault(result)
        return CommandResult(
            text="display_state:ok", json_data=result.model_dump(mode="json")
        )


display_state_get: DisplayStateGetCommand = DisplayStateGetCommand()
