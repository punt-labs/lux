"""Unit tests for AddressRendering -- the Display's identity-rendering seam."""

from __future__ import annotations

from punt_lux.display.replica.address_book import AddressBook
from punt_lux.display.replica.address_rendering import AddressRendering
from punt_lux.display.replica.frame import Frame
from punt_lux.domain.hub_id import HubId
from punt_lux.domain.id_separator import ID_SEPARATOR

_PEMBROKE_1 = HubId("pembroke", 100)
_PEMBROKE_2 = HubId("pembroke", 200)
_OKINOS = HubId("okinos", 300)


def _rendering(*noted: tuple[HubId, str]) -> AddressRendering:
    """An AddressRendering over a book with the given connections noted."""
    book = AddressBook()
    for hub, key in noted:
        book.note_connection(hub, key)
    return AddressRendering(book)


def _frame(hub: HubId, frame_id: str, title: str) -> Frame:
    """A minimal on-screen frame owned by ``hub``."""
    return Frame(
        hub=hub,
        frame_id=frame_id,
        title=title,
        owner_fds={1},
        scenes={},
        scene_order=[],
    )


class TestHiddenIdFor:
    def test_prepends_the_hub_wire_token_to_the_composed_key(self) -> None:
        rendering = _rendering((_PEMBROKE_1, "c1"))
        hidden = rendering.hidden_id_for(_PEMBROKE_1, "frame-1")
        assert hidden == f"{_PEMBROKE_1.wire_token}{ID_SEPARATOR}frame-1"

    def test_namespaces_a_key_that_already_carries_the_separator(self) -> None:
        """A menu_id is a Rung-2 composed id and carries the separator; the Hub
        dimension is prepended, not rejected."""
        rendering = _rendering((_PEMBROKE_1, "c1"))
        menu_id = f"conn-7{ID_SEPARATOR}ticket-3"
        hidden = rendering.hidden_id_for(_PEMBROKE_1, menu_id)
        assert hidden == f"{_PEMBROKE_1.wire_token}{ID_SEPARATOR}{menu_id}"

    def test_two_hubs_minting_the_same_key_get_distinct_hidden_ids(self) -> None:
        rendering = _rendering((_PEMBROKE_1, "c1"), (_PEMBROKE_2, "c2"))
        first = rendering.hidden_id_for(_PEMBROKE_1, "vox")
        second = rendering.hidden_id_for(_PEMBROKE_2, "vox")
        assert first != second


class TestTitleFor:
    def test_a_lone_item_reads_as_its_plain_label(self) -> None:
        rendering = _rendering((_PEMBROKE_1, "c1"))
        assert rendering.title_for(_PEMBROKE_1, "Vox") == "Vox"

    def test_with_no_connections_noted_an_item_still_reads_plain(self) -> None:
        assert AddressRendering(AddressBook()).title_for(_PEMBROKE_1, "Vox") == "Vox"

    def test_two_hubs_on_one_host_disambiguate_by_numbered_hostname(self) -> None:
        rendering = _rendering((_PEMBROKE_1, "c1"), (_PEMBROKE_2, "c2"))
        assert rendering.title_for(_PEMBROKE_1, "Vox") == "pembroke :: Vox"
        assert rendering.title_for(_PEMBROKE_2, "Vox") == "pembroke (2) :: Vox"

    def test_two_hubs_on_different_hosts_disambiguate_by_hostname(self) -> None:
        rendering = _rendering((_PEMBROKE_1, "c1"), (_OKINOS, "c2"))
        assert rendering.title_for(_PEMBROKE_1, "Vox") == "pembroke :: Vox"
        assert rendering.title_for(_OKINOS, "Vox") == "okinos :: Vox"

    def test_a_departed_second_hub_returns_the_survivor_to_plain(self) -> None:
        book = AddressBook()
        book.note_connection(_PEMBROKE_1, "c1")
        book.note_connection(_OKINOS, "c2")
        book.forget_connection(_OKINOS, "c2")
        assert AddressRendering(book).title_for(_PEMBROKE_1, "Vox") == "Vox"


class TestFrameProjection:
    def test_frame_title_disambiguates_two_hubs_same_title(self) -> None:
        rendering = _rendering((_PEMBROKE_1, "c1"), (_PEMBROKE_2, "c2"))
        one = _frame(_PEMBROKE_1, "vox", "Vox")
        two = _frame(_PEMBROKE_2, "vox", "Vox")
        assert rendering.frame_title(one) == "pembroke :: Vox"
        assert rendering.frame_title(two) == "pembroke (2) :: Vox"

    def test_a_lone_frame_keeps_its_plain_title(self) -> None:
        rendering = _rendering((_PEMBROKE_1, "c1"))
        assert rendering.frame_title(_frame(_PEMBROKE_1, "vox", "Vox")) == "Vox"

    def test_frame_window_ids_differ_across_hubs_with_the_same_frame_id(
        self,
    ) -> None:
        rendering = _rendering((_PEMBROKE_1, "c1"), (_PEMBROKE_2, "c2"))
        one = _frame(_PEMBROKE_1, "vox", "Vox")
        two = _frame(_PEMBROKE_2, "vox", "Vox")
        assert rendering.frame_window_id(one) != rendering.frame_window_id(two)

    def test_frame_window_id_prepends_the_hub_to_the_frame_id(self) -> None:
        rendering = _rendering((_PEMBROKE_1, "c1"))
        frame = _frame(_PEMBROKE_1, "vox", "Vox")
        assert (
            rendering.frame_window_id(frame)
            == f"{_PEMBROKE_1.wire_token}{ID_SEPARATOR}vox"
        )
