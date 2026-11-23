"""Direct tests for :class:`DisplayScreenshotCommand` (PL-TT-5)."""

from __future__ import annotations

import asyncio

from punt_lux.commands import Ctx, ScreenshotOps, display_screenshot
from punt_lux.operations import OpError
from punt_lux.operations.models.display_probe import Screenshot
from tests.commands._family_stubs import StubScreenshotOps
from tests.commands._scene_stub import identity


def test_a_capture_renders_its_path_as_text_and_json() -> None:
    ops = StubScreenshotOps(result=Screenshot(path="/tmp/lux-screenshots/a.png"))
    ctx: Ctx[ScreenshotOps] = Ctx(ops=ops, identity=identity())

    result = asyncio.run(display_screenshot(ctx))

    assert result.error is False
    assert result.text == "/tmp/lux-screenshots/a.png"
    assert result.json_data == {"path": "/tmp/lux-screenshots/a.png"}


def test_a_refusal_renders_the_error_line() -> None:
    ops = StubScreenshotOps(
        result=OpError(code="rejected", reason="a screenshot is already waiting")
    )
    ctx: Ctx[ScreenshotOps] = Ctx(ops=ops, identity=identity())

    result = asyncio.run(display_screenshot(ctx))

    assert result.error is True
    assert "already waiting" in result.text


def test_routes_the_zero_arg_call_through_to_screenshot() -> None:
    ops = StubScreenshotOps(
        result=OpError(code="rejected", reason="pin routing arg"),
    )
    ctx: Ctx[ScreenshotOps] = Ctx(ops=ops, identity=identity())

    asyncio.run(display_screenshot(ctx))

    assert ops.last_call == {"method": "screenshot"}
