"""Direct tests for :class:`DisplayWindowGetCommand` (PL-TT-5)."""

from __future__ import annotations

import asyncio

from punt_lux.commands import Ctx, WindowOps, display_window_get
from punt_lux.operations import OpError, WindowSettings
from tests.commands._family_stubs import StubWindowOps
from tests.commands._scene_stub import identity


def _settings() -> WindowSettings:
    return WindowSettings(opacity=1.0, font_scale=1.0, decorated=True, fps_idle=30.0)


def test_success_renders_window_line() -> None:
    ops = StubWindowOps(get_result=_settings())
    ctx: Ctx[WindowOps] = Ctx(ops=ops, identity=identity())

    result = asyncio.run(display_window_get(ctx))

    assert result.text == "window:ok"


def test_display_unavailable_renders_shared_fault_line() -> None:
    ops = StubWindowOps(get_result=OpError(code="display_unavailable", reason="down"))
    ctx: Ctx[WindowOps] = Ctx(ops=ops, identity=identity())

    result = asyncio.run(display_window_get(ctx))

    assert result.text == "not running"


def test_routes_the_zero_arg_call_through_to_get_window_settings() -> None:
    ops = StubWindowOps(get_result=_settings())
    ctx: Ctx[WindowOps] = Ctx(ops=ops, identity=identity())

    asyncio.run(display_window_get(ctx))

    assert ops.last_call == {"method": "get_window_settings"}
