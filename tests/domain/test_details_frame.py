"""DetailsFrame — the one name for the frame a client's Details window lives in."""

from __future__ import annotations

import pytest

from punt_lux.domain.hub.connection_scoped_id import ConnectionScopedId
from punt_lux.domain.hub.details_frame import DetailsFrame
from punt_lux.domain.ids import ConnectionId


class TestTheRawId:
    def test_it_names_the_client_it_describes(self) -> None:
        frame = DetailsFrame(ConnectionId("c1"))

        assert frame.raw_id == "lux.client-details.c1"

    def test_two_clients_never_share_a_raw_id(self) -> None:
        first = DetailsFrame(ConnectionId("c1"))
        second = DetailsFrame(ConnectionId("c2"))

        assert first.raw_id != second.raw_id


class TestTheScopedId:
    def test_it_is_the_key_the_scene_installer_composes(self) -> None:
        conn = ConnectionId("c1")

        assert DetailsFrame(conn).scoped_id == ConnectionScopedId.compose(
            conn, "lux.client-details.c1"
        )

    def test_two_clients_never_share_a_scoped_id(self) -> None:
        first = DetailsFrame(ConnectionId("c1"))
        second = DetailsFrame(ConnectionId("c2"))

        assert first.scoped_id != second.scoped_id

    def test_a_client_whose_name_extends_anothers_does_not_collide(self) -> None:
        short = DetailsFrame(ConnectionId("c1"))
        long = DetailsFrame(ConnectionId("c10"))

        assert short.scoped_id != long.scoped_id


class TestWhatIsRefused:
    def test_a_connection_id_carrying_the_separator_is_refused(self) -> None:
        """The composed key must round-trip, so the raw id may not smuggle a rule."""
        with pytest.raises(ValueError, match="separator"):
            _ = DetailsFrame(ConnectionId("a\x1fb")).scoped_id


class TestThePresentation:
    def test_it_places_a_scene_in_the_frame_named_by_the_raw_id(self) -> None:
        frame = DetailsFrame(ConnectionId("c1"))

        placed = frame.presentation("lux — client details")

        assert (placed.frame_id, placed.frame_title) == (
            frame.raw_id,
            "lux — client details",
        )


class TestTableId:
    def test_names_the_table_the_scene_holds(self) -> None:
        assert DetailsFrame(ConnectionId("c1")).TABLE_ID == "lux.client-details.table"

    def test_is_the_same_for_every_connection(self) -> None:
        first = DetailsFrame(ConnectionId("c1"))
        second = DetailsFrame(ConnectionId("c2"))

        assert first.TABLE_ID == second.TABLE_ID
