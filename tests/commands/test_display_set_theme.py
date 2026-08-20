"""Direct tests for :class:`DisplaySetThemeCommand` (PL-TT-5)."""

from __future__ import annotations

import asyncio

from punt_lux.commands import Ctx, ThemeOps, display_set_theme
from punt_lux.operations import OpError, SetThemeRequest, ThemeState
from tests.commands._family_stubs import StubThemeOps
from tests.commands._scene_stub import identity


def _request() -> SetThemeRequest | OpError:
    return SetThemeRequest.parse("darcula")


def test_success_renders_new_theme() -> None:
    ops = StubThemeOps(set_result=ThemeState(theme="darcula", available=["darcula"]))
    ctx: Ctx[ThemeOps] = Ctx(ops=ops, identity=identity())

    result = asyncio.run(display_set_theme(ctx, _request()))

    assert result.text == "theme:darcula"


def test_display_unavailable_renders_shared_fault_line() -> None:
    ops = StubThemeOps(set_result=OpError(code="display_unavailable", reason="down"))
    ctx: Ctx[ThemeOps] = Ctx(ops=ops, identity=identity())

    result = asyncio.run(display_set_theme(ctx, _request()))

    assert result.text == "not running"
