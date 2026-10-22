"""MenuFrames — the frames a connection's menu items open, named before a click."""

from __future__ import annotations

from punt_lux.domain.hub.connection_scoped_id import ConnectionScopedId
from punt_lux.domain.hub.details_frame import DetailsFrame
from punt_lux.domain.hub.menu_frames import MenuFrames
from punt_lux.domain.hub.session_callback import SessionCallback
from punt_lux.domain.ids import ConnectionId

_CONN = ConnectionId("c1")


class TestACallbacksFrame:
    def test_a_registered_frame_is_scoped_to_the_owner(self) -> None:
        callback = SessionCallback(id="beads", label="Beads", frame_id="beads-lux")

        assert MenuFrames(_CONN).of(callback) == ConnectionScopedId.compose(
            _CONN, "beads-lux"
        )

    def test_no_registered_frame_opens_none(self) -> None:
        callback = SessionCallback(id="run", label="Run")

        assert MenuFrames(_CONN).of(callback) is None

    def test_the_same_local_frame_under_two_owners_never_collides(self) -> None:
        callback = SessionCallback(id="beads", label="Beads", frame_id="beads-lux")

        first = MenuFrames(ConnectionId("c1")).of(callback)
        second = MenuFrames(ConnectionId("c2")).of(callback)

        assert first != second


class TestTheDetailsFrame:
    def test_it_is_the_frame_the_details_scene_is_stored_under(self) -> None:
        assert MenuFrames(_CONN).details == DetailsFrame(_CONN).scoped_id
