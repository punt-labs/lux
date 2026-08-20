"""Direct tests for :class:`DisplayModeGetCommand` (PL-TT-5)."""

from __future__ import annotations

import asyncio

import pytest

from punt_lux.commands import Ctx, DisplayModeOps, display_mode_get
from punt_lux.operations import DisplayModeState, OpError
from tests.commands._family_stubs import StubDisplayModeOps
from tests.commands._scene_stub import identity


def test_success_renders_display_line() -> None:
    ops = StubDisplayModeOps(read_result=DisplayModeState(mode="on"))
    ctx: Ctx[DisplayModeOps] = Ctx(ops=ops, identity=identity())

    result = asyncio.run(display_mode_get(ctx, "/repo"))

    assert result.text == "display:on"


def test_op_error_raises_value_error() -> None:
    """Preserves the shipped tool's ``raise ValueError`` on a malformed repo."""
    ops = StubDisplayModeOps(read_result=OpError(code="invalid_request", reason="bad"))
    ctx: Ctx[DisplayModeOps] = Ctx(ops=ops, identity=identity())

    with pytest.raises(ValueError, match="bad"):
        asyncio.run(display_mode_get(ctx, ""))


def test_routes_repo_through_to_ops() -> None:
    ops = StubDisplayModeOps(read_result=DisplayModeState(mode="on"))
    ctx: Ctx[DisplayModeOps] = Ctx(ops=ops, identity=identity())

    asyncio.run(display_mode_get.execute(ctx, "/repo"))

    assert ops.last_call == {"method": "read_display_mode", "repo": "/repo"}
