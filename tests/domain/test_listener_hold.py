"""A listener's hold on a dial's reader slot is handed out once and given back once.

The slot makes the hold and hands it to the listener alone, so a settle is always the
holder's. A dial born held gives its hold out once; a dial not born held gives none;
and a hold's release frees the slot once, so a stale release can never free a slot a
later reader holds.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

import pytest

from punt_lux.domain.hub import bounded_ask
from punt_lux.domain.hub.dial_drain import DialDrain
from punt_lux.domain.hub.drain_result import DrainIncompleteError
from punt_lux.domain.hub.reader_slot import InlineHolder
from punt_lux.domain.hub.settle_errors import UnendedDialError
from punt_lux.domain.hub.settler import Settler
from tests.domain.display_double import Call, Display
from tests.link_access import bare_connection, drop_route, reading_of

if TYPE_CHECKING:
    from collections.abc import Iterator

    from punt_lux.domain.hub.display_connection import DisplayConnection
    from punt_lux.domain.hub.reader_slot import ReaderSlot


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

        hold = slot.hold_born(drop_route, drop_route)

        assert isinstance(hold.settler, Settler)

    def test_it_is_handed_out_once(self, connection: DisplayConnection) -> None:
        born = connection.open_listening()
        assert born is not None
        slot = connection.reading(born)
        assert slot is not None
        slot.hold_born(drop_route, drop_route)

        with pytest.raises(RuntimeError, match="no unclaimed born hold"):
            slot.hold_born(drop_route, drop_route)

    def test_a_dial_that_was_not_born_held_has_none(
        self, connection: DisplayConnection
    ) -> None:
        connection.open()

        with pytest.raises(RuntimeError, match="no unclaimed born hold"):
            reading_of(connection).hold_born(drop_route, drop_route)


class TestTheClaimedHold:
    def test_a_claim_gives_the_hold_and_a_second_claim_none(
        self, connection: DisplayConnection
    ) -> None:
        connection.open()
        slot = reading_of(connection)

        first = slot.claim_for_listener(drop_route, drop_route)
        second = slot.claim_for_listener(drop_route, drop_route)

        assert (first is not None, second) == (True, None)

    def test_a_hold_is_given_back_once(self, connection: DisplayConnection) -> None:
        connection.open()
        slot = reading_of(connection)
        hold = slot.claim_for_listener(drop_route, drop_route)
        assert hold is not None
        hold.release()

        with pytest.raises(RuntimeError, match="given back once"):
            hold.release()

    def test_a_stale_release_does_not_free_a_slot_a_later_reader_holds(
        self, connection: DisplayConnection
    ) -> None:
        connection.open()
        slot = reading_of(connection)
        stale = slot.claim_for_listener(drop_route, drop_route)
        assert stale is not None
        stale.release()
        assert (
            slot.claim_for_listener(drop_route, drop_route) is not None
        )  # a later holder

        with pytest.raises(RuntimeError):
            stale.release()

        assert slot.has_listener


def _holder_of(slot: ReaderSlot) -> object:
    """What holds the slot now: the seam the holder's own tests read."""
    return slot._holder


class TestTheInlineHolder:
    """One value says an inline read holds the slot, and which thread it is."""

    def test_the_slot_names_the_thread_that_reads_inline_and_is_free_after(
        self, connection: DisplayConnection
    ) -> None:
        connection.open()
        slot = reading_of(connection)

        with slot.inline(drop_route) as settler:
            assert settler is not None
            assert _holder_of(slot) == InlineHolder(threading.get_ident())
        assert _holder_of(slot) == "none"

    def test_an_end_the_inline_holder_makes_itself_never_waits_for_itself(
        self, connection: DisplayConnection, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(bounded_ask, "SETTLE_BOUND", 60.0)
        connection.open()
        generation = connection.require()
        slot = reading_of(connection)

        def ask_while_reading() -> None:
            with slot.inline(drop_route):
                generation.request_hub()
                slot.ask_settle(drop_route, "hub", may_wait=True)  # its own debt

        call = Call(ask_while_reading)

        assert call.wait(5.0), "the holder waited on itself for the bound"
        assert generation.is_settled  # the release honoured the debt
        assert call.error is None

    def test_another_threads_end_waits_on_the_holder_up_to_the_bound(
        self, connection: DisplayConnection, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(bounded_ask, "SETTLE_BOUND", 0.2)
        connection.open()
        generation = connection.require()
        slot = reading_of(connection)
        inside, leave = threading.Event(), threading.Event()

        def hold() -> None:
            with slot.inline(drop_route):
                inside.set()
                leave.wait(10.0)

        holder = Call(hold)
        assert inside.wait(3.0)
        generation.request_hub()
        try:
            asking = Call(lambda: slot.ask_settle(drop_route, "hub", may_wait=True))
            assert asking.wait(5.0)
            assert generation.is_settled  # the bound captured it, undrained
        finally:
            leave.set()
            holder.wait()


class TestTheSettlersCause:
    def test_a_dial_nobody_ended_has_no_cause_to_settle_by(
        self, connection: DisplayConnection, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        connection.open()
        generation = connection.require()

        def incomplete(_this: DialDrain, _generation: object) -> bool:
            msg = "a writer holds the socket"
            raise DrainIncompleteError(msg)

        monkeypatch.setattr(DialDrain, "run", incomplete)
        settler = Settler(generation, drop_route, lambda _g, _c: True, lambda _c: True)

        with pytest.raises(UnendedDialError, match="no one ended or asked"):
            settler.settle()
