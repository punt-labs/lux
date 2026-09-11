"""FrameOps -- the Protocol every frame_remove implementer satisfies structurally."""

from __future__ import annotations

from punt_lux.commands._frame_ports import FrameOps
from punt_lux.domain.ids import ConnectionId
from punt_lux.operations import Ok, Scope


class _Implementer:
    """Satisfies ``FrameOps`` by shape alone -- no explicit inheritance."""

    def remove_frame(self, frame_id: str, *, scope: Scope) -> Ok:
        del frame_id, scope
        return Ok()


def test_a_matching_shape_satisfies_the_protocol_structurally() -> None:
    assert isinstance(_Implementer(), FrameOps)


def test_an_object_missing_remove_frame_does_not_satisfy_it() -> None:
    assert not isinstance(object(), FrameOps)


def test_remove_frame_takes_a_plain_frame_id_not_a_value_object() -> None:
    # Finding 7 (PR #464): the public Protocol takes a caller-facing string,
    # never the internal FrameTarget bundle -- proving it can be called with
    # a bare frame_id + scope, matching every sibling Ops Protocol's shape.
    result = _Implementer().remove_frame("board", scope=Scope(ConnectionId("c1")))
    assert result == Ok()


def test_an_object_with_only_the_retired_close_frame_name_does_not_satisfy_it() -> None:
    """Rename train (lux-81t3.6): no alias survives for the retired name."""

    class _OldNamedImplementer:
        def close_frame(self, frame_id: str, *, scope: Scope) -> Ok:
            del frame_id, scope
            return Ok()

    assert not isinstance(_OldNamedImplementer(), FrameOps)
