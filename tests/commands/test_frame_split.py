"""Tests for the frame_raise and frame_close commands."""

from __future__ import annotations

import asyncio
from typing import cast

from punt_lux.commands import Ctx, FrameOps, frame_close, frame_raise
from punt_lux.domain.hub.client_identity import ClientIdentity
from punt_lux.operations import FrameRaise, Ok, OpError

from ._family_stubs import StubFrameOps

_WHO = ClientIdentity(kind="cli", name="test")


def _stub(result: object) -> StubFrameOps:
    # Cast: StubFrameOps carries typed slots for one preset outcome across the
    # three FrameOps returns; the tests supply whichever result they read.
    return StubFrameOps(result=cast("Ok | OpError | None", result))


def test_frame_raise_returns_ok_envelope_when_raised() -> None:
    ops = _stub(FrameRaise(frame_id="f1", raised=True))
    ctx: Ctx[FrameOps] = Ctx(ops=ops, identity=_WHO)
    result = asyncio.run(frame_raise(ctx, "f1"))
    assert not result.error
    assert result.text == "raised:True"


def test_frame_raise_renders_fault_on_op_error() -> None:
    ops = _stub(OpError(code="display_unavailable", reason="down"))
    ctx: Ctx[FrameOps] = Ctx(ops=ops, identity=_WHO)
    result = asyncio.run(frame_raise(ctx, "f1"))
    assert result.error
    assert result.text == "not running"


def test_frame_close_returns_ok_envelope() -> None:
    ops = _stub(Ok())
    ctx: Ctx[FrameOps] = Ctx(ops=ops, identity=_WHO)
    result = asyncio.run(frame_close(ctx, "f1"))
    assert not result.error
    assert result.text == "closed:f1"
