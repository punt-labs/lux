"""Direct tests for :class:`DisplayStateGetCommand` (PL-TT-5)."""

from __future__ import annotations

import asyncio

from punt_lux.commands import Ctx
from punt_lux.commands.display_state_get import DisplayStateOps, display_state_get
from punt_lux.domain.ids import ConnectionId
from punt_lux.operations import DisplayStateSnapshot, OpError, Scope
from punt_lux.operations.models.display_state import FramePresentation
from tests.commands._family_stubs import StubDisplayStateOps
from tests.commands._scene_stub import identity

_SCOPE = Scope(ConnectionId("c1"))
_SNAPSHOT = DisplayStateSnapshot(
    scenes={},
    frames=[
        FramePresentation(
            frame_id="f1", visibility="on_screen", active_tab=None, cascade_index=0
        )
    ],
)


def test_success_renders_the_ok_line() -> None:
    ops = StubDisplayStateOps(get_result=_SNAPSHOT)
    ctx: Ctx[DisplayStateOps] = Ctx(ops=ops, identity=identity())

    result = asyncio.run(display_state_get(ctx, scope=_SCOPE))

    assert result.text == "display_state:ok"
    assert result.error is False
    assert result.json_data == _SNAPSHOT.model_dump(mode="json")


def test_display_unavailable_renders_shared_fault_line() -> None:
    fault = OpError(code="display_unavailable", reason="down")
    ops = StubDisplayStateOps(get_result=fault)
    ctx: Ctx[DisplayStateOps] = Ctx(ops=ops, identity=identity())

    result = asyncio.run(display_state_get(ctx, scope=_SCOPE))

    assert result.error is True


def test_routes_the_call_through_with_the_callers_scope() -> None:
    ops = StubDisplayStateOps(get_result=_SNAPSHOT)
    ctx: Ctx[DisplayStateOps] = Ctx(ops=ops, identity=identity())

    asyncio.run(display_state_get(ctx, scope=_SCOPE))

    assert ops.last_call == {"method": "get_display_state", "scope": _SCOPE}


def test_execute_returns_the_typed_snapshot_directly() -> None:
    ops = StubDisplayStateOps(get_result=_SNAPSHOT)
    ctx: Ctx[DisplayStateOps] = Ctx(ops=ops, identity=identity())

    result = asyncio.run(display_state_get.execute(ctx, scope=_SCOPE))

    assert result is _SNAPSHOT
