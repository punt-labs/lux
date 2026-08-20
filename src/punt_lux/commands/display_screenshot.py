"""``display screenshot`` -- refuse cleanly; framebuffer capture is unsupported.

The underlying ``ctx.ops.screenshot`` always returns ``OpError(rejected)``
because framebuffer capture is unresolved below the message layer. The
command preserves that behavior: it does not invent an implementation.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Self, final

from punt_lux.commands._faults import render_fault
from punt_lux.commands._result import CommandResult
from punt_lux.operations import OpError

if TYPE_CHECKING:
    from punt_lux.commands._ports import Ctx, ScreenshotOps
    from punt_lux.operations.models.display_probe import Screenshot


@final
class DisplayScreenshotCommand:
    """Refuse a screenshot request; capture is unsupported below the message layer."""

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    async def execute(self, ctx: Ctx[ScreenshotOps]) -> Screenshot | OpError:
        """Return the typed screenshot -- which is always an ``OpError`` today."""
        return await asyncio.to_thread(ctx.ops.screenshot)

    async def __call__(self, ctx: Ctx[ScreenshotOps]) -> CommandResult:
        """Run :meth:`execute` and render its outcome into the shared envelope.

        Renders every outcome through :func:`render_fault` -- the shipped tool
        line for the unsupported case is ``"error: <reason>"`` (the fault
        vocabulary's generic branch), and any future success path will land
        with a proper path field the adapters can render separately.
        """
        result = await self.execute(ctx)
        if isinstance(result, OpError):
            return render_fault(result)
        return CommandResult(
            text=str(result.path), json_data={"path": str(result.path)}
        )


display_screenshot: DisplayScreenshotCommand = DisplayScreenshotCommand()
