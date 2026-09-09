"""FrameAccessorDeps -- the bundle FrameAccessor.__new__ takes."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from punt_lux.client.frame_deps import FrameAccessorDeps
from punt_lux.domain.hub.client_identity import ClientIdentity
from punt_lux.domain.ids import ConnectionId
from punt_lux.operations import Ok, Scope

_IDENTITY = ClientIdentity(kind="cli", name="frame-deps-test")
_SCOPE = Scope(ConnectionId("c1"))


class _StubFrameOps:
    """A minimal ``FrameOps``-shaped stub -- construction only, never called."""

    def close_frame(self, frame_id: str, *, scope: Scope) -> Ok:
        del frame_id, scope
        return Ok()


def test_fields_round_trip() -> None:
    ops = _StubFrameOps()
    deps = FrameAccessorDeps(ops, _IDENTITY, _SCOPE)
    assert deps.ops is ops
    assert deps.identity is _IDENTITY
    assert deps.scope is _SCOPE


def test_is_frozen() -> None:
    deps = FrameAccessorDeps(_StubFrameOps(), _IDENTITY, _SCOPE)
    with pytest.raises(FrozenInstanceError):
        deps.scope = Scope(ConnectionId("c2"))  # type: ignore[misc]  # proving frozen=True raises
