"""Direct tests for :class:`DisplayWindowSetCommand` (PL-TT-5)."""

from __future__ import annotations

import asyncio

from punt_lux.commands import Ctx, WindowOps, display_window_set
from punt_lux.operations import OpError, WindowSettings, WindowSettingsPatch
from tests.commands._family_stubs import StubWindowOps
from tests.commands._scene_stub import identity


def _patch() -> WindowSettingsPatch | OpError:
    return WindowSettingsPatch.parse({"opacity": 0.75})


def _settings() -> WindowSettings:
    return WindowSettings(opacity=0.75, font_scale=1.0, decorated=True, fps_idle=30.0)


def test_success_renders_window_line() -> None:
    ops = StubWindowOps(set_result=_settings())
    ctx: Ctx[WindowOps] = Ctx(ops=ops, identity=identity())

    result = asyncio.run(display_window_set(ctx, _patch()))

    assert result.text == "window:ok"


def test_routes_patch_through_to_ops() -> None:
    ops = StubWindowOps(set_result=_settings())
    ctx: Ctx[WindowOps] = Ctx(ops=ops, identity=identity())
    patch = _patch()

    asyncio.run(display_window_set.execute(ctx, patch))

    assert ops.last_call == {"method": "set_window_settings", "patch": patch}
