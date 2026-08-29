"""``display mode-set`` -- write a project's per-repo display mode.

Preserves the historical ``ValueError`` on a malformed mode/repo -- the MCP
tool (``tools/display_write_tools.py:set_display_mode``) and the
characterization suite (``tests/characterization/test_exerciser.py::
TestToolExceptionPropagates``) both pin this as the one tool whose exception
propagates unmolested, proving the exerciser does not swallow a raise. The
CLI verb avoids ever reaching this raise for its own malformed-input case by
building the request with ``DisplayModeRequest.parse`` (returning
``Request | OpError``) and checking ``isinstance(..., OpError)`` itself
before calling this command, the same shape ``scene_show``/``scene_update``
use -- see ``cli/display.py``.
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
