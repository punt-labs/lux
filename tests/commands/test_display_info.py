"""Direct tests for :class:`DisplayInfoCommand` (PL-TT-5)."""

from __future__ import annotations

import asyncio

from punt_lux.commands import Ctx, DisplayInfoOps, display_info
from punt_lux.operations import DisplayInfo, OpError
from tests.commands._family_stubs import StubDisplayInfoOps
from tests.commands._scene_stub import identity


def _info() -> DisplayInfo:
    return DisplayInfo(
        backend="glfw",
        window_width=800,
        window_height=600,
        fps=60.0,
        pid=1234,
        uptime_seconds=1.5,
        protocol_version="1",
        element_kinds=25,
    )


def test_success_renders_backend_line() -> None:
    ops = StubDisplayInfoOps(result=_info())
    ctx: Ctx[DisplayInfoOps] = Ctx(ops=ops, identity=identity())

    result = asyncio.run(display_info(ctx))

    assert result.text == "display:glfw"
    assert result.error is False


def test_display_unavailable_renders_shared_fault_line() -> None:
    ops = StubDisplayInfoOps(result=OpError(code="display_unavailable", reason="down"))
    ctx: Ctx[DisplayInfoOps] = Ctx(ops=ops, identity=identity())

    result = asyncio.run(display_info(ctx))

    assert result.text == "not running"


def test_routes_call_through_to_ops() -> None:
    ops = StubDisplayInfoOps(result=_info())
    ctx: Ctx[DisplayInfoOps] = Ctx(ops=ops, identity=identity())

    asyncio.run(display_info.execute(ctx))

    assert ops.last_call == {"method": "get_display_info"}
