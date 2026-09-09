"""FrameCloseRequest -- the bundle every frame_close call site builds."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from punt_lux.commands._frame_close_request import FrameCloseRequest
from punt_lux.commands._ports import Ctx, FrameOps
from punt_lux.domain.hub.client_identity import ClientIdentity
from punt_lux.domain.ids import ConnectionId
from punt_lux.operations import Scope

from ._family_stubs import StubFrameOps

_WHO = ClientIdentity(kind="cli", name="frame-close-request-test")
_SCOPE = Scope(ConnectionId("c1"))


def test_fields_round_trip() -> None:
    ctx: Ctx[FrameOps] = Ctx(ops=StubFrameOps(), identity=_WHO)
    request = FrameCloseRequest(ctx, "board", _SCOPE)
    assert request.ctx is ctx
    assert request.frame_id == "board"
    assert request.scope is _SCOPE


def test_is_frozen() -> None:
    ctx: Ctx[FrameOps] = Ctx(ops=StubFrameOps(), identity=_WHO)
    request = FrameCloseRequest(ctx, "board", _SCOPE)
    with pytest.raises(FrozenInstanceError):
        request.frame_id = "other"  # type: ignore[misc]  # proving frozen=True raises
