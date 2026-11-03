"""A settle or release in a ``finally`` may not replace the failure that led to it."""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING

import pytest

from punt_lux.domain.hub.batch_sender import BatchSendError
from punt_lux.domain.hub.dial_generation import DialGeneration
from punt_lux.domain.hub.dial_reader import DialReader
from punt_lux.domain.hub.finally_guard import FinallyGuard
from punt_lux.domain.hub.reader_slot import ReaderSlot
from punt_lux.domain.hub.settler import Settler
from tests.domain.display_double import Display
from tests.domain.test_retire_cause import _linked, _scene
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
    def test_when_the_body_succeeds_the_actions_failure_propagates(self) -> None:
        with (
            pytest.raises(RuntimeError, match="own failure"),
            FinallyGuard(_broken, "settling"),
        ):
            pass

    def test_a_body_that_succeeds_inside_someone_elses_except_still_propagates(
        self,
    ) -> None:
        """The probe of the review: the thread's state is not the body's outcome."""
        with pytest.raises(RuntimeError, match="own failure"):
            try:
                raise KeyError("being recovered from")
            except KeyError:
                with FinallyGuard(_broken, "letting go"):
                    pass

    def test_when_the_body_fails_the_original_goes_on_and_the_other_is_logged(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with (
            caplog.at_level(logging.ERROR),
            pytest.raises(KeyError),
            FinallyGuard(_broken, "settling"),
        ):
            raise KeyError("the original")

        assert "settling failed while handling" in caplog.text
        assert "the action's own failure" in caplog.text
        assert "the original" in caplog.text

    def test_the_guard_never_swallows_the_body_it_ran_after(self) -> None:
        ran: list[str] = []
        with pytest.raises(KeyError), FinallyGuard(lambda: ran.append("action"), "x"):
            raise KeyError("body")

        assert ran == ["action"]


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

    def test_a_release_failing_after_a_clean_settle_inside_a_recovery_propagates(
        self, display: Display, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The replicator's ``except BatchSendError`` heal drops the failed dial."""
        link = _linked(display, listening=False)
        generation = generation_of(link)
        monkeypatch.setattr(ReaderSlot, "_release", _broken)

        with pytest.raises(RuntimeError, match="own failure"):
            try:
                raise BatchSendError(OSError("send failed"), generation.ref)
            except BatchSendError as failure:
                assert failure.dial is not None
                link.drop_if_current(failure.dial, cause="display")

    def test_a_release_failing_after_a_clean_settle_in_a_failed_write_propagates(
        self, display: Display, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``_write_locked``'s except calls ``_failed``, which asks for the settle."""
        link = _linked(display, listening=False)
        generation = generation_of(link)
        monkeypatch.setattr(ReaderSlot, "_release", _broken)
        display.sockets[-1].fail_next_send = True

        with pytest.raises(RuntimeError, match="own failure"):
            generation.send_scene(_scene("a"))
