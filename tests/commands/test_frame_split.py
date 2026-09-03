"""Tests for the frame_close command."""

from __future__ import annotations

import asyncio
from typing import cast

from punt_lux.commands import Ctx, FrameOps, frame_close
from punt_lux.domain.hub.client_identity import ClientIdentity
from punt_lux.operations import Ok, OpError

from ._family_stubs import StubFrameOps

_WHO = ClientIdentity(kind="cli", name="test")


def _stub(result: object) -> StubFrameOps:
    # Cast: StubFrameOps carries a typed slot for one preset outcome; the test
    # supplies whichever result it reads.
    return StubFrameOps(result=cast("Ok | OpError | None", result))


def test_frame_close_returns_ok_envelope() -> None:
    ops = _stub(Ok())
    ctx: Ctx[FrameOps] = Ctx(ops=ops, identity=_WHO)
    result = asyncio.run(frame_close(ctx, "f1"))
    assert not result.error
    assert result.text == "closed:f1"
