"""``display mode-get`` -- read a project's per-repo display mode.

Text shape matches the shipped ``display_mode`` MCP tool byte-for-byte --
``"display:on"``/``"display:off"`` on success -- and raises ``ValueError`` on
a malformed repo, so the CLI/adapter surface preserves the historical
exception path.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Self, final

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

        Preserves the shipped tool's ``raise ValueError(reason)`` on any
        ``OpError`` -- historical exception path for a malformed repo argument.
        """
        result = await self.execute(ctx, repo)
        if isinstance(result, OpError):
            raise ValueError(result.reason)
        return CommandResult(
            text=f"display:{result.mode}",
            json_data={"mode": result.mode},
        )


display_mode_get: DisplayModeGetCommand = DisplayModeGetCommand()
