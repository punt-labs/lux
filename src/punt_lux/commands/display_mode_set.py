"""``display mode-set`` -- write a project's per-repo display mode.

Preserves the historical ``ValueError`` on a malformed mode/repo.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Self, final

from punt_lux.commands._result import CommandResult
from punt_lux.operations import DisplayModeState, OpError

if TYPE_CHECKING:
    from punt_lux.commands._ports import Ctx, DisplayModeOps
    from punt_lux.operations import DisplayModeRequest


@final
class DisplayModeSetCommand:
    """Write the caller's project display mode; eager-connect on turning on."""

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    async def execute(
        self, ctx: Ctx[DisplayModeOps], request: DisplayModeRequest | OpError
    ) -> DisplayModeState | OpError:
        """Persist the new mode, or return the parse/write error."""
        return await asyncio.to_thread(ctx.ops.write_display_mode, request)

    async def __call__(
        self, ctx: Ctx[DisplayModeOps], request: DisplayModeRequest | OpError
    ) -> CommandResult:
        """Run :meth:`execute` and render its outcome into the shared envelope."""
        result = await self.execute(ctx, request)
        if isinstance(result, OpError):
            raise ValueError(result.reason)
        return CommandResult(
            text=f"display:{result.mode}",
            json_data={"mode": result.mode},
        )


display_mode_set: DisplayModeSetCommand = DisplayModeSetCommand()
