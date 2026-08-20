"""``display mode-get`` -- read a project's per-repo display mode.

Text shape matches the shipped ``display_mode`` MCP tool byte-for-byte --
``"display:on"``/``"display:off"`` on success.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Self, final

from punt_lux.commands._faults import render_error
from punt_lux.commands._result import CommandResult
from punt_lux.operations import DisplayModeState, OpError

if TYPE_CHECKING:
    from punt_lux.commands._ports import Ctx, DisplayModeOps


@final
class DisplayModeGetCommand:
    """Read a project's per-repo display mode from ``<repo>/.punt-labs/lux.md``."""

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    async def execute(
        self, ctx: Ctx[DisplayModeOps], repo: str
    ) -> DisplayModeState | OpError:
        """Return the mode config, or an ``OpError`` for a malformed request."""
        return await asyncio.to_thread(ctx.ops.read_display_mode, repo)

    async def __call__(self, ctx: Ctx[DisplayModeOps], repo: str) -> CommandResult:
        """Run :meth:`execute` and render its outcome into the shared envelope.

        A malformed ``repo`` is always ``invalid_request`` (never a display-
        proxy fault code -- this reads a local config file, not the display),
        so :func:`render_error` -- not :func:`~punt_lux.commands._faults.
        render_fault` -- is the matching vocabulary, same shape as every other
        command's ``OpError`` path.
        """
        result = await self.execute(ctx, repo)
        if isinstance(result, OpError):
            return render_error(result)
        return CommandResult(
            text=f"display:{result.mode}",
            json_data={"mode": result.mode},
        )


display_mode_get: DisplayModeGetCommand = DisplayModeGetCommand()
