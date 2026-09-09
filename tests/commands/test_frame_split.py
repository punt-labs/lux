"""Tests for the frame_close command."""

from __future__ import annotations

import asyncio
from typing import cast

from punt_lux.commands import Ctx, FrameOps, frame_close
from punt_lux.commands._frame_close_request import FrameCloseRequest
from punt_lux.domain.hub.client_identity import ClientIdentity
from punt_lux.domain.ids import ConnectionId
from punt_lux.operations import Ok, OpError, Scope

from ._family_stubs import StubFrameOps

_WHO = ClientIdentity(kind="cli", name="test")
_SCOPE = Scope(ConnectionId("test-conn"))


def _stub(result: object) -> StubFrameOps:
    # Cast: StubFrameOps carries a typed slot for one preset outcome; the test
    # supplies whichever result it reads.
    return StubFrameOps(result=cast("Ok | OpError | None", result))


def test_frame_close_returns_ok_envelope() -> None:
    ops = _stub(Ok())
    ctx: Ctx[FrameOps] = Ctx(ops=ops, identity=_WHO)
    result = asyncio.run(frame_close(FrameCloseRequest(ctx, "f1", _SCOPE)))
    assert not result.error
    assert result.text == "closed:f1"


def test_frame_close_routes_the_callers_own_scope() -> None:
    ops = _stub(Ok())
    ctx: Ctx[FrameOps] = Ctx(ops=ops, identity=_WHO)
    asyncio.run(frame_close(FrameCloseRequest(ctx, "f1", _SCOPE)))
    assert ops.last_call["scope"] is _SCOPE
