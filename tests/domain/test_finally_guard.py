"""A settle or release in a ``finally`` may not replace the failure that led to it."""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING

import pytest

from punt_lux.domain.hub.dial_generation import DialGeneration
from punt_lux.domain.hub.dial_reader import DialReader
from punt_lux.domain.hub.finally_guard import FinallyGuard
from punt_lux.domain.hub.reader_slot import ReaderSlot
from punt_lux.domain.hub.settler import Settler
from tests.domain.display_double import Display
from tests.domain.test_retire_cause import _linked
from tests.link_access import drop_route, generation_of, reading_of

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture
def display() -> Iterator[Display]:
    d = Display()
    yield d
    d.close()


def _broken(*_args: object) -> None:
    msg = "the action's own failure"
    raise RuntimeError(msg)


class TestTheGuard:
    def test_with_nothing_in_flight_the_actions_failure_propagates(self) -> None:
        with pytest.raises(RuntimeError, match="own failure"):
            FinallyGuard.run(_broken, "settling")

    def test_with_a_failure_in_flight_the_original_goes_on_and_the_other_is_logged(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.ERROR), pytest.raises(KeyError):
            try:
                raise KeyError("the original")
            finally:
                FinallyGuard.run(_broken, "settling")

        assert "settling failed while handling" in caplog.text
        assert "the action's own failure" in caplog.text
        assert "the original" in caplog.text


class TestTheDoorsThatSettleInAFinally:
    def test_a_reader_whose_read_and_settle_both_fail_raises_the_read(
        self,
        display: Display,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        link = _linked(display, listening=False)
        generation = generation_of(link)
        hold = reading_of(link).claim_for_listener(drop_route, drop_route)
        assert hold is not None

        def read_breaks(_this: DialGeneration, _timeout: float) -> bytes | None:
            msg = "the read broke"
            raise KeyError(msg)

        monkeypatch.setattr(DialGeneration, "poll_chunk", read_breaks)
        monkeypatch.setattr(Settler, "settle", _broken)

        with (
            caplog.at_level(logging.ERROR),
            pytest.raises(KeyError, match="read broke"),
        ):
            DialReader(generation, hold.settler, drop_route, threading.Event()).run()

        assert "the action's own failure" in caplog.text

    def test_an_inline_read_whose_body_and_release_both_fail_raises_the_body(
        self,
        display: Display,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        link = _linked(display, listening=False)
        slot = reading_of(link)
        monkeypatch.setattr(ReaderSlot, "_release", _broken)

        with (
            caplog.at_level(logging.ERROR),
            pytest.raises(LookupError),
            slot.inline(drop_route),
        ):
            raise LookupError("the body")

        assert "letting go of the slot failed" in caplog.text

    def test_a_release_that_fails_alone_still_propagates(
        self, display: Display, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        link = _linked(display, listening=False)
        slot = reading_of(link)
        monkeypatch.setattr(ReaderSlot, "_release", _broken)

        with pytest.raises(RuntimeError, match="own failure"), slot.inline(drop_route):
            pass
