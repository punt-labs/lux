"""The small value types of the dial and the batch say what they hold, and no more.

``DialEnds`` names its two same-shaped callables, ``Drained`` and ``CutShort`` carry
every input at construction, ``_read_now`` gives three answers three shapes, and the
settler asks the dial who is ending it once.
"""

from __future__ import annotations

import inspect
import logging
from dataclasses import FrozenInstanceError
from typing import TYPE_CHECKING

import pytest

from punt_lux.domain.hub.batch_judge import BatchJudge, _Written
from punt_lux.domain.hub.dial_drain import DialDrain
from punt_lux.domain.hub.dial_generation import DialEnds, DialGeneration
from punt_lux.domain.hub.drain_result import CutShort, Drained, DrainIncompleteError
from punt_lux.domain.hub.hub_store_factory import HubStoreFactory
from punt_lux.domain.hub.settle_errors import UnendedDialError
from punt_lux.domain.hub.transaction_errors import JudgeReusedError
from punt_lux.domain.hub.write_refusals import UnheldTargetError
from punt_lux.domain.programmer_error import ProgrammerError
from punt_lux.protocol import PongMessage
from punt_lux.protocol.elements import TableElement
from tests.domain.display_double import Display
from tests.domain.test_nesting_cap_at_the_seam import _OWNER, _SCENE
from tests.domain.test_retire_cause import _linked
from tests.link_access import generation_of, reading_of

if TYPE_CHECKING:
    from collections.abc import Iterator

    from punt_lux.domain.hub.connection_closed import RetireCause
    from punt_lux.domain.hub.settlement import Settlement


@pytest.fixture
def display() -> Iterator[Display]:
    d = Display()
    yield d
    d.close()


class TestTheTypesAreClosed:
    @pytest.mark.parametrize("cls", [DialEnds, Drained, CutShort, _Written])
    def test_each_is_final(self, cls: type) -> None:
        assert getattr(cls, "__final__", False) is True

    def test_dial_ends_are_named_where_they_are_made(self) -> None:
        kinds = {p.kind for p in inspect.signature(DialEnds).parameters.values()}

        assert kinds == {inspect.Parameter.KEYWORD_ONLY}

    def test_what_a_batch_wrote_cannot_be_reassigned(self) -> None:
        table = TableElement(id="t", columns=["c"], rows=[["r"]])
        judge = BatchJudge(lambda _e, _p: None, [])
        judge.admit(table, {"rows": [["s"]]})
        (entry,) = judge._touched.values()

        field = "props"
        with pytest.raises(FrozenInstanceError):
            setattr(entry, field, {})


class TestACutShortLookKnowsWhatItLostTheRaceTo:
    def test_it_takes_every_input_at_construction(self) -> None:
        cut = CutShort("pair", OSError("reset"), captured=True, is_tls=False)

        assert (cut.endpoint, cut.captured, cut.is_tls) == ("pair", True, False)

    def test_a_remote_reset_is_loud(self, caplog: pytest.LogCaptureFixture) -> None:
        cut = CutShort("tls", ConnectionResetError(), captured=False, is_tls=True)

        with caplog.at_level(logging.DEBUG):
            cut.report()

        assert [r.levelno for r in caplog.records] == [logging.WARNING]

    def test_a_look_that_lost_to_the_capture_is_quiet(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        cut = CutShort("pair", ValueError("fd"), captured=True, is_tls=True)

        with caplog.at_level(logging.DEBUG):
            cut.report()

        assert [r.levelno for r in caplog.records] == [logging.DEBUG]


class TestAReadGivesThreeAnswersThreeShapes:
    def test_nothing_more_now_is_no_bytes_and_not_ended(self, display: Display) -> None:
        generation = generation_of(_linked(display, listening=False))

        assert generation._socket._read_now() == Drained(b"", ended=False)

    def test_bytes_are_a_chunk_that_has_not_ended(self, display: Display) -> None:
        generation = generation_of(_linked(display, listening=False))
        display.peer.send(PongMessage(ts=1.0))

        look = _read_until_bytes(generation)

        assert (bool(look.chunk), look.ended) == (True, False)

    def test_the_streams_end_is_ended_with_no_bytes(self, display: Display) -> None:
        generation = generation_of(_linked(display, listening=False))
        display.peer.close()

        look = _read_until_ended(generation)

        assert look == Drained(b"", ended=True)


def _read_until_bytes(generation: DialGeneration) -> Drained:
    for _ in range(50):
        look = generation._socket._read_now()
        if look.chunk:
            return look
    msg = "no bytes arrived"
    raise AssertionError(msg)


def _read_until_ended(generation: DialGeneration) -> Drained:
    for _ in range(50):
        look = generation._socket._read_now()
        if look.ended:
            return look
    msg = "the end never arrived"
    raise AssertionError(msg)


class TestTheBatchJudgeServesOneBatch:
    def test_a_second_roll_back_raises_a_programmer_error(self) -> None:
        table = TableElement(id="t", columns=["c"], rows=[["r"]])
        judge = BatchJudge(lambda _e, _p: None, [])
        judge.admit(table, {"rows": [["s"]]})
        judge.roll_back()

        with pytest.raises(JudgeReusedError, match="settles once") as caught:
            judge.roll_back()

        assert isinstance(caught.value, ProgrammerError)

    def test_a_commit_after_a_roll_back_is_refused(self) -> None:
        judge = BatchJudge(lambda _e, _p: None, [])
        judge.roll_back()

        with pytest.raises(JudgeReusedError):
            judge.commit()


class TestTheFinalStateCheck:
    def test_an_element_no_scene_holds_is_refused_not_skipped(self) -> None:
        store = HubStoreFactory().display
        store.replace_scene(_OWNER, _SCENE, [TableElement(id="held", columns=["c"])])
        loose = TableElement(id="loose", columns=["c"])

        with pytest.raises(UnheldTargetError):
            store.write_seam._require_final_state_within_cap([loose])


class TestTheSettlerAsksTheDialOnce:
    def test_a_dial_nothing_ends_has_no_cause_to_settle_by(
        self, display: Display, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        link = _linked(display, listening=False)
        hold = reading_of(link).claim_for_listener(_drop, _drop)
        assert hold is not None
        monkeypatch.setattr(DialDrain, "run", _incomplete)  # the look cannot be made

        with pytest.raises(UnendedDialError, match="no cause to settle by") as caught:
            hold.settler.settle()

        assert isinstance(caught.value, ProgrammerError)

    def test_an_undrained_end_captures_with_the_cause_that_stands(
        self, display: Display, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        link = _linked(display, listening=False)
        generation = generation_of(link)
        hold = reading_of(link).claim_for_listener(_drop, _drop)
        assert hold is not None
        captured: list[RetireCause] = []
        real = DialGeneration.mark_closed

        def spy(this: DialGeneration, cause: RetireCause) -> Settlement:
            captured.append(cause)
            return real(this, cause)

        monkeypatch.setattr(DialGeneration, "mark_closed", spy)
        generation.end("display")  # recorded first: the one that stands

        won = hold.settler.end_stream("unresponsive")

        assert (won, captured) == (False, ["display"])


def _incomplete(_drain: object, _generation: object) -> bool:
    raise DrainIncompleteError("a writer held the socket")


def _drop(_generation: object, _message: object) -> None:
    """A route that drops what a drain would route."""
