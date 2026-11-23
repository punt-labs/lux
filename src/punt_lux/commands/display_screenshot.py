"""``display screenshot`` -- capture the display's next painted frame to a PNG."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Self, final

from punt_lux.commands._faults import render_fault
from punt_lux.commands._result import CommandResult
from punt_lux.wire.operations import OpError

if TYPE_CHECKING:
    from punt_lux.wire.operations.display_probe import Screenshot
    from punt_lux.wire.ops import Ctx, ScreenshotOps


@final
class DisplayScreenshotCommand:
    """Capture the next painted frame; the result names the PNG on the display host."""

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    async def execute(self, ctx: Ctx[ScreenshotOps]) -> Screenshot | OpError:
        """Return the typed screenshot, or the error the display answered with."""
        return await asyncio.to_thread(ctx.ops.screenshot)

    async def __call__(self, ctx: Ctx[ScreenshotOps]) -> CommandResult:
        """Run :meth:`execute` and render its outcome into the shared envelope.

        A failure renders through :func:`render_fault` as ``"error: <reason>"``;
        a capture renders as its path, which is on the display's host.
        """
        result = await self.execute(ctx)
        if isinstance(result, OpError):
            return render_fault(result)
        return CommandResult(
            text=str(result.path), json_data={"path": str(result.path)}
        )


display_screenshot: DisplayScreenshotCommand = DisplayScreenshotCommand()
