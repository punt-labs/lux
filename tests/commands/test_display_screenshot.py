"""Direct tests for :class:`DisplayScreenshotCommand` (PL-TT-5).

Framebuffer capture is unresolved below the message layer (DES-028); the
underlying op always returns ``OpError(rejected)``. These tests pin that
behavior at the command layer.
"""

from __future__ import annotations

import asyncio

from punt_lux.commands import Ctx, ScreenshotOps, display_screenshot
from punt_lux.operations import OpError
from tests.commands._family_stubs import StubScreenshotOps
from tests.commands._scene_stub import identity


def test_unsupported_renders_the_shipped_error_line() -> None:
    ops = StubScreenshotOps(
        result=OpError(
            code="rejected",
            reason="screenshot capture is not supported by the display; see DES-028",
        )
    )
    ctx: Ctx[ScreenshotOps] = Ctx(ops=ops, identity=identity())

    result = asyncio.run(display_screenshot(ctx))

    assert result.error is True
    assert "screenshot capture is not supported" in result.text
