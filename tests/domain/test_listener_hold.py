"""A listener's hold on a dial's reader slot is handed out once and given back once.

The slot makes the hold and hands it to the listener alone, so a settle is always the
holder's. A dial born held gives its hold out once; a dial not born held gives none;
and a hold's release frees the slot once, so a stale release can never free a slot a
later reader holds.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from punt_lux.domain.hub.settler import Settler
from tests.domain.display_double import Display
from tests.link_access import bare_connection, drop_route, reading_of

if TYPE_CHECKING:
    from collections.abc import Iterator

    from punt_lux.domain.hub.display_connection import DisplayConnection


@pytest.fixture
def connection() -> Iterator[DisplayConnection]:
    display = Display()
    made = bare_connection(display, 1.0)
    yield made
    made.close()
    display.close()


class TestTheBornHold:
    def test_a_dial_born_held_hands_its_hold_out(
        self, connection: DisplayConnection
    ) -> None:
        born = connection.open_listening()
        assert born is not None
        slot = connection.reading(born)
        assert slot is not None

        hold = slot.hold_born(drop_route)

        assert isinstance(hold.settler, Settler)

    def test_it_is_handed_out_once(self, connection: DisplayConnection) -> None:
        born = connection.open_listening()
        assert born is not None
        slot = connection.reading(born)
        assert slot is not None
        slot.hold_born(drop_route)

        with pytest.raises(RuntimeError, match="no unclaimed born hold"):
            slot.hold_born(drop_route)

    def test_a_dial_that_was_not_born_held_has_none(
        self, connection: DisplayConnection
    ) -> None:
        connection.open()

        with pytest.raises(RuntimeError, match="no unclaimed born hold"):
            reading_of(connection).hold_born(drop_route)


class TestTheClaimedHold:
    def test_a_claim_gives_the_hold_and_a_second_claim_none(
        self, connection: DisplayConnection
    ) -> None:
        connection.open()
        slot = reading_of(connection)

        first = slot.claim_for_listener(drop_route)
        second = slot.claim_for_listener(drop_route)

        assert (first is not None, second) == (True, None)

    def test_a_hold_is_given_back_once(self, connection: DisplayConnection) -> None:
        connection.open()
        slot = reading_of(connection)
        hold = slot.claim_for_listener(drop_route)
        assert hold is not None
        hold.release(drop_route)

        with pytest.raises(RuntimeError, match="given back once"):
            hold.release(drop_route)

    def test_a_stale_release_does_not_free_a_slot_a_later_reader_holds(
        self, connection: DisplayConnection
    ) -> None:
        connection.open()
        slot = reading_of(connection)
        stale = slot.claim_for_listener(drop_route)
        assert stale is not None
        stale.release(drop_route)
        assert slot.claim_for_listener(drop_route) is not None  # a later holder

        with pytest.raises(RuntimeError):
            stale.release(drop_route)

        assert slot.has_listener
