"""Direct tests for :class:`FrameSetStateCommand` (PL-TT-5)."""

from __future__ import annotations

import asyncio

from punt_lux.commands import Ctx, FrameOps, frame_set_state
from punt_lux.operations import FrameStatePatch, Ok, OpError
from tests.commands._family_stubs import StubFrameOps
from tests.commands._scene_stub import identity


def _patch() -> FrameStatePatch | OpError:
    return FrameStatePatch.parse({"minimized": True})


def test_success_renders_ok() -> None:
    ops = StubFrameOps(result=Ok())
    ctx: Ctx[FrameOps] = Ctx(ops=ops, identity=identity())

    result = asyncio.run(frame_set_state(ctx, "frame-1", _patch()))

    assert result.text == "ok"
    assert result.error is False


def test_display_unavailable_renders_shared_fault_line() -> None:
    ops = StubFrameOps(result=OpError(code="display_unavailable", reason="down"))
    ctx: Ctx[FrameOps] = Ctx(ops=ops, identity=identity())

    result = asyncio.run(frame_set_state(ctx, "frame-1", _patch()))

    assert result.text == "not running"
    assert result.error is True


def test_execute_returns_the_typed_outcome_with_no_envelope() -> None:
    ops = StubFrameOps(result=Ok())
    ctx: Ctx[FrameOps] = Ctx(ops=ops, identity=identity())

    result = asyncio.run(frame_set_state.execute(ctx, "frame-1", _patch()))

    assert result == Ok()


def test_routes_frame_id_and_patch_through_to_ops() -> None:
    ops = StubFrameOps(result=Ok())
    ctx: Ctx[FrameOps] = Ctx(ops=ops, identity=identity())
    patch = _patch()

    asyncio.run(frame_set_state.execute(ctx, "frame-1", patch))

    assert ops.last_call == {"frame_id": "frame-1", "patch": patch}
