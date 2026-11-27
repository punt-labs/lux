"""FrameAccessor -- remove a frame under the scope it was built with."""

from __future__ import annotations

import asyncio

from punt_lux.client.frame import FrameAccessor
from punt_lux.kernel.connection_id import ConnectionId
from punt_lux.wire.model.client_identity import ClientIdentity
from punt_lux.wire.operations import Ok, Scope

_IDENTITY = ClientIdentity(kind="cli", name="frame-accessor-test")
_SCOPE = Scope.in_process(ConnectionId("c1"))


class _RecordingFrameOps:
    """A ``FrameOps``-shaped double that records what it was asked to remove."""

    removed: list[tuple[str, Scope]]

    def __new__(cls) -> _RecordingFrameOps:
        self = super().__new__(cls)
        self.removed = []
        return self

    def remove_frame(self, frame_id: str, *, scope: Scope) -> Ok:
        self.removed.append((frame_id, scope))
        return Ok()


def test_remove_passes_the_frame_and_the_scope_it_was_built_with() -> None:
    ops = _RecordingFrameOps()
    accessor = FrameAccessor(ops, _IDENTITY, _SCOPE)

    result = asyncio.run(accessor.remove("f1"))

    assert result == Ok()
    assert ops.removed == [("f1", _SCOPE)]
