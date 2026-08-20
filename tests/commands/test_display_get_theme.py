"""Direct tests for :class:`DisplayGetThemeCommand` (PL-TT-5)."""

from __future__ import annotations

import asyncio

from punt_lux.commands import Ctx, ThemeOps, display_get_theme
from punt_lux.operations import OpError, ThemeState
from tests.commands._family_stubs import StubThemeOps
from tests.commands._scene_stub import identity


def test_success_renders_theme_line() -> None:
    ops = StubThemeOps(get_result=ThemeState(theme="darcula", available=["darcula"]))
    ctx: Ctx[ThemeOps] = Ctx(ops=ops, identity=identity())

    result = asyncio.run(display_get_theme(ctx))

    assert result.text == "theme:darcula"
    assert result.error is False


def test_display_unavailable_renders_shared_fault_line() -> None:
    ops = StubThemeOps(get_result=OpError(code="display_unavailable", reason="down"))
    ctx: Ctx[ThemeOps] = Ctx(ops=ops, identity=identity())

    result = asyncio.run(display_get_theme(ctx))

    assert result.text == "not running"
