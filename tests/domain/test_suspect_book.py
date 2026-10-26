"""SuspectBook -- who is a suspect of a death, from the dials that settled before it."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from punt_lux.domain.hub.settlement import Settlement
from punt_lux.domain.hub.suspect_book import SuspectBook
from punt_lux.domain.ids import SceneId

if TYPE_CHECKING:
    import pytest

    from punt_lux.domain.hub.connection_closed import RetireCause


def _ids(*names: str) -> frozenset[SceneId]:
    return frozenset(SceneId(n) for n in names)


def _settled(cause: RetireCause, *owed: str, acked: bool = False) -> Settlement:
    return Settlement(tuple(SceneId(n) for n in owed), acked, cause)


class TestADialTheHubEnded:
    def test_it_charges_nothing_and_its_owed_scenes_are_carried(self) -> None:
        book = SuspectBook()

        book.settle(_settled("hub", "p"), "pair-1")

        assert book.deaths.take() is None
        assert book.carried == _ids("p")

    def test_what_it_owed_joins_what_earlier_dials_carried(self) -> None:
        book = SuspectBook()
        book.settle(_settled("hub", "p"), "pair-1")

        book.settle(_settled("hub", "q"), "pair-2")

        assert book.carried == _ids("p", "q")

    def test_an_ack_read_on_it_cleared_what_earlier_dials_carried(self) -> None:
        book = SuspectBook()
        book.settle(_settled("hub", "p"), "pair-1")

        book.settle(_settled("hub", "q", acked=True), "pair-2")

        assert book.carried == _ids("q")


class TestADialTheDisplayEnded:
    def test_it_charges_what_it_owed_and_the_book_is_then_empty(self) -> None:
        book = SuspectBook()
        book.settle(_settled("hub", "p"), "pair-1")

        book.settle(_settled("display", "q"), "pair-2")

        death = book.deaths.take()
        assert death is not None
        assert death.suspects == _ids("p", "q")
        assert death.cause == "display"
        assert book.carried == frozenset()

    def test_with_an_empty_ledger_it_charges_the_carried_set(self) -> None:
        book = SuspectBook()
        book.settle(_settled("hub", "p"), "pair-1")

        book.settle(_settled("display"), "pair-2")

        death = book.deaths.take()
        assert death is not None
        assert death.suspects == _ids("p")

    def test_owing_nothing_with_nothing_carried_charges_nothing(self) -> None:
        book = SuspectBook()

        book.settle(_settled("display"), "pair-1")

        assert book.deaths.take() is None

    def test_an_ack_read_on_it_clears_the_carried_set_before_the_charge(self) -> None:
        book = SuspectBook()
        book.settle(_settled("hub", "p"), "pair-1")

        book.settle(_settled("display", "r", acked=True), "pair-2")

        death = book.deaths.take()
        assert death is not None
        assert death.suspects == _ids("r")


class TestADialTheHubGaveUpOn:
    def test_it_charges_like_a_death_and_carries_what_it_charged(self) -> None:
        book = SuspectBook()
        book.settle(_settled("hub", "p"), "pair-1")

        book.settle(_settled("unresponsive", "q"), "pair-2")

        death = book.deaths.take()
        assert death is not None
        assert death.suspects == _ids("p", "q")
        assert death.cause == "unresponsive"
        assert book.carried == _ids("p", "q")

    def test_it_owing_nothing_carries_nothing_new(self) -> None:
        book = SuspectBook()

        book.settle(_settled("unresponsive"), "pair-1")

        assert book.deaths.take() is None
        assert book.carried == frozenset()

    def test_the_next_display_end_charges_what_it_left(self) -> None:
        book = SuspectBook()
        book.settle(_settled("unresponsive", "p"), "pair-1")
        assert book.deaths.take() is not None

        book.settle(_settled("display", "q"), "pair-2")

        death = book.deaths.take()
        assert death is not None
        assert death.suspects == _ids("p", "q")


class TestTheDeathsWaitingToBeCharged:
    def test_they_come_out_oldest_first_and_each_once(self) -> None:
        book = SuspectBook()
        book.settle(_settled("display", "a"), "pair-1")
        book.settle(_settled("display", "b"), "pair-2")

        first, second, nothing = (
            book.deaths.take(),
            book.deaths.take(),
            book.deaths.take(),
        )

        assert first is not None
        assert second is not None
        assert first.suspects == _ids("a")
        assert second.suspects == _ids("b")
        assert nothing is None

    def test_past_the_warning_mark_every_death_is_kept_and_the_book_says_so(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        book = SuspectBook()

        with caplog.at_level(logging.WARNING):
            for turn in range(70):
                book.settle(_settled("display", f"s{turn}"), f"pair-{turn}")

        kept = []
        while (death := book.deaths.take()) is not None:
            kept.append(death)
        assert len(kept) == 70
        assert "wait to be charged" in caplog.text
