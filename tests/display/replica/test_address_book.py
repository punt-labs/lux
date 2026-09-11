"""Unit tests for AddressBook — the Display's one Rung-3 identity minter."""

from __future__ import annotations

import pytest

from punt_lux.display.replica.address_book import AddressBook
from punt_lux.domain.hub_id import HubId
from punt_lux.domain.id_separator import ID_SEPARATOR

_PEMBROKE_1 = HubId("pembroke", 100)
_PEMBROKE_2 = HubId("pembroke", 200)
_OKINOS = HubId("okinos", 300)


class TestAddressFor:
    def test_mints_an_address_from_the_given_keys_and_labels(self) -> None:
        book = AddressBook()
        book.note_connection(_PEMBROKE_1, "vox-session")
        addr = book.address_for(
            _PEMBROKE_1, "vox-session", "lux", "music-player", "Vox"
        )
        assert addr.hub.key == _PEMBROKE_1.wire_token
        assert addr.connection.key == "vox-session"
        assert addr.connection.label == "lux"
        assert addr.leaf.key == "music-player"
        assert addr.leaf.label == "Vox"

    def test_passes_the_connection_and_leaf_labels_through_unchanged(self) -> None:
        book = AddressBook()
        book.note_connection(_PEMBROKE_1, "c1")
        addr = book.address_for(_PEMBROKE_1, "c1", "lux (2)", "leaf1", "Beads")
        assert addr.connection.label == "lux (2)"
        assert addr.leaf.label == "Beads"

    def test_an_unregistered_hub_labels_itself_by_bare_hostname(self) -> None:
        book = AddressBook()
        addr = book.address_for(_PEMBROKE_1, "c1", "lux", "leaf1", "Vox")
        assert addr.hub.label == "pembroke"

    def test_propagates_lux_address_rejection_of_a_separator_bearing_key(
        self,
    ) -> None:
        """LuxAddress owns the validation; this proves address_for wires it."""
        book = AddressBook()
        with pytest.raises(ValueError, match="unit separator"):
            book.address_for(
                _PEMBROKE_1, f"c1{ID_SEPARATOR}evil", "lux", "leaf1", "Vox"
            )


class TestHubLabelNumbering:
    def test_a_solo_hub_gets_the_bare_hostname(self) -> None:
        book = AddressBook()
        book.note_connection(_PEMBROKE_1, "c1")
        addr = book.address_for(_PEMBROKE_1, "c1", "lux", "leaf1", "Vox")
        assert addr.hub.label == "pembroke"

    def test_two_hubs_on_the_same_host_get_des_064_style_numbering(self) -> None:
        book = AddressBook()
        book.note_connection(_PEMBROKE_1, "c1")
        book.note_connection(_PEMBROKE_2, "c2")
        first = book.address_for(_PEMBROKE_1, "c1", "lux", "leaf1", "Vox")
        second = book.address_for(_PEMBROKE_2, "c2", "lux", "leaf1", "Vox")
        assert first.hub.label == "pembroke"
        assert second.hub.label == "pembroke (2)"

    def test_two_hubs_on_different_hosts_each_get_their_own_bare_hostname(self) -> None:
        book = AddressBook()
        book.note_connection(_PEMBROKE_1, "c1")
        book.note_connection(_OKINOS, "c2")
        first = book.address_for(_PEMBROKE_1, "c1", "lux", "leaf1", "Vox")
        second = book.address_for(_OKINOS, "c2", "lux", "leaf1", "Vox")
        assert first.hub.label == "pembroke"
        assert second.hub.label == "okinos"

    def test_a_departed_hub_frees_its_label_for_the_survivor(self) -> None:
        book = AddressBook()
        book.note_connection(_PEMBROKE_1, "c1")
        book.note_connection(_PEMBROKE_2, "c2")
        book.forget_connection(_PEMBROKE_1, "c1")
        survivor = book.address_for(_PEMBROKE_2, "c2", "lux", "leaf1", "Vox")
        assert survivor.hub.label == "pembroke"

    def test_forgetting_an_unnoted_connection_is_not_an_error(self) -> None:
        book = AddressBook()
        book.forget_connection(_PEMBROKE_1, "c1")  # no raise


class TestHubAmbiguous:
    def test_false_with_no_live_hubs(self) -> None:
        assert AddressBook().hub_ambiguous() is False

    def test_false_with_exactly_one_live_hub(self) -> None:
        book = AddressBook()
        book.note_connection(_PEMBROKE_1, "c1")
        assert book.hub_ambiguous() is False

    def test_true_with_two_live_hubs_even_on_different_hosts(self) -> None:
        book = AddressBook()
        book.note_connection(_PEMBROKE_1, "c1")
        book.note_connection(_OKINOS, "c2")
        assert book.hub_ambiguous() is True

    def test_returns_to_false_once_a_hub_fully_departs(self) -> None:
        book = AddressBook()
        book.note_connection(_PEMBROKE_1, "c1")
        book.note_connection(_OKINOS, "c2")
        book.forget_connection(_OKINOS, "c2")
        assert book.hub_ambiguous() is False


class TestConnectionAmbiguous:
    def test_false_with_one_connection_on_the_hub(self) -> None:
        book = AddressBook()
        book.note_connection(_PEMBROKE_1, "c1")
        assert book.connection_ambiguous(_PEMBROKE_1) is False

    def test_true_with_two_connections_on_the_same_hub(self) -> None:
        book = AddressBook()
        book.note_connection(_PEMBROKE_1, "c1")
        book.note_connection(_PEMBROKE_1, "c2")
        assert book.connection_ambiguous(_PEMBROKE_1) is True

    def test_is_scoped_to_one_hub_not_the_whole_book(self) -> None:
        book = AddressBook()
        book.note_connection(_PEMBROKE_1, "c1")
        book.note_connection(_OKINOS, "c2")
        book.note_connection(_OKINOS, "c3")
        assert book.connection_ambiguous(_PEMBROKE_1) is False
        assert book.connection_ambiguous(_OKINOS) is True

    def test_false_for_a_hub_the_book_has_never_seen(self) -> None:
        assert AddressBook().connection_ambiguous(_PEMBROKE_1) is False


class TestFullyDisambiguatedTitleFlow:
    def test_matches_the_target_examples(self) -> None:
        book = AddressBook()

        # One Hub, one connection: "Vox".
        book.note_connection(_PEMBROKE_1, "vox-session")
        solo = book.address_for(
            _PEMBROKE_1, "vox-session", "lux", "music-player", "Vox"
        )
        solo_title = solo.title(
            hub_ambiguous=book.hub_ambiguous(),
            connection_ambiguous=book.connection_ambiguous(_PEMBROKE_1),
        )
        assert solo_title == "Vox"

        # Two connections sharing a repo, one Hub: "lux (2) :: Vox".
        book.note_connection(_PEMBROKE_1, "beads-session")
        second_conn = book.address_for(
            _PEMBROKE_1, "beads-session", "lux (2)", "music-player", "Vox"
        )
        second_title = second_conn.title(
            hub_ambiguous=book.hub_ambiguous(),
            connection_ambiguous=book.connection_ambiguous(_PEMBROKE_1),
        )
        assert second_title == "lux (2) :: Vox"

        # A second Hub arrives: "pembroke :: lux (2) :: Vox".
        book.note_connection(_OKINOS, "other-session")
        with_hub = book.address_for(
            _PEMBROKE_1, "beads-session", "lux (2)", "music-player", "Vox"
        )
        with_hub_title = with_hub.title(
            hub_ambiguous=book.hub_ambiguous(),
            connection_ambiguous=book.connection_ambiguous(_PEMBROKE_1),
        )
        assert with_hub_title == "pembroke :: lux (2) :: Vox"
