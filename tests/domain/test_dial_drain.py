"""DialDrain -- the last look at a dial's socket routes everything it holds, once."""

from __future__ import annotations

import logging
import select
from typing import TYPE_CHECKING

import pytest

from punt_lux.domain.hub import dial_drain
from punt_lux.domain.hub.dial_drain import DialDrain
from punt_lux.domain.hub.lock_discipline_error import LockDisciplineError
from punt_lux.domain.hub.reply_sink import ReplySink
from punt_lux.domain.hub.reply_waiters import ReplyOutOfOrderError
from punt_lux.domain.ids import SceneId
from punt_lux.protocol import AckMessage, ObserverMessage, PongMessage, encode_message
from tests.domain.display_double import Display
from tests.domain.test_retire_cause import _linked, _scene
from tests.link_access import deaths_of, generation_of, writer_of

if TYPE_CHECKING:
    from collections.abc import Iterator

    from punt_lux.domain.hub.dial_generation import DialGeneration
    from punt_lux.protocol import Message


@pytest.fixture
def display() -> Iterator[Display]:
    d = Display()
    yield d
    d.close()


def _routed_by_a_drain(generation: DialGeneration) -> list[Message]:
    routed: list[Message] = []
    DialDrain(lambda _generation, msg: routed.append(msg)).run(generation)
    return routed


def _generation(display: Display) -> DialGeneration:
    return generation_of(_linked(display, listening=False))


class TestWhatTheDrainRoutes:
    def test_everything_the_socket_holds_is_routed_in_order(
        self, display: Display
    ) -> None:
        generation = _generation(display)
        display.peer.send(AckMessage(scene_id="a"), AckMessage(scene_id="b"))

        routed = _routed_by_a_drain(generation)

        assert [m.scene_id for m in routed if isinstance(m, AckMessage)] == ["a", "b"]

    def test_frames_the_reader_took_off_the_socket_and_did_not_route_are_routed(
        self, display: Display
    ) -> None:
        generation = _generation(display)
        buffered = encode_message(AckMessage(scene_id="a")) + encode_message(
            AckMessage(scene_id="b")
        )
        generation.messages(buffered)  # fed to the frame buffer, never iterated

        routed = _routed_by_a_drain(generation)

        assert [m.scene_id for m in routed if isinstance(m, AckMessage)] == ["a", "b"]

    def test_an_empty_socket_routes_nothing_and_does_not_wait(
        self, display: Display
    ) -> None:
        assert _routed_by_a_drain(_generation(display)) == []

    def test_what_arrived_before_the_display_hung_up_is_still_routed(
        self, display: Display
    ) -> None:
        generation = _generation(display)
        display.peer.send(PongMessage(ts=1.0))
        display.peer.close()

        routed = _routed_by_a_drain(generation)

        assert routed == [PongMessage(ts=1.0)]


class TestWhatTheDrainSurvives:
    def test_an_event_whose_route_raises_costs_only_its_own_message(
        self, display: Display, caplog: pytest.LogCaptureFixture
    ) -> None:
        generation = _generation(display)
        display.peer.send(
            ObserverMessage(topic="bad", payload={}),
            ObserverMessage(topic="good", payload={}),
        )
        seen: list[str] = []

        def route(_generation: DialGeneration, msg: Message) -> None:
            assert isinstance(msg, ObserverMessage)
            if msg.topic == "bad":
                raise ValueError("this one cannot be routed")
            seen.append(msg.topic)

        with caplog.at_level(logging.ERROR):
            DialDrain(route).run(generation)

        assert seen == ["good"]
        assert "Drain route failed" in caplog.text

    def test_a_route_that_breaks_a_rule_is_not_swallowed(
        self, display: Display
    ) -> None:
        generation = _generation(display)
        display.peer.send(ObserverMessage(topic="any", payload={}))

        def route(_generation: DialGeneration, _msg: Message) -> None:
            raise LockDisciplineError("planted: a lock taken in the wrong order")

        with pytest.raises(LockDisciplineError):
            DialDrain(route).run(generation)

    def test_a_frame_that_cannot_be_decoded_ends_the_drain_and_says_so(
        self, display: Display, caplog: pytest.LogCaptureFixture
    ) -> None:
        generation = _generation(display)
        display.peer.send_raw(b"\x00\x00\x00\x05not-json")

        with caplog.at_level(logging.ERROR):
            routed = _routed_by_a_drain(generation)

        assert routed == []
        assert "could not be read past" in caplog.text


class TestASkewedAckLeavesTheLedgerWhole:
    """An ack that is not the one owed next is evidence of a skew, never a pop."""

    def test_the_sink_pops_an_ack_only_when_it_matches_the_head(self) -> None:
        sink = ReplySink()
        sink.owe_ack("a")
        sink.owe_ack("b")

        with pytest.raises(ReplyOutOfOrderError):
            sink.deliver(AckMessage(scene_id="b"))

        assert sink.owed_acks == 2

    def test_a_drain_that_reads_the_wrong_ack_captures_the_whole_ledger(
        self, display: Display
    ) -> None:
        link = _linked(display, listening=False)
        writer_of(link).send_scene(_scene("a"))
        writer_of(link).send_scene(_scene("b"))
        display.peer.send(AckMessage(scene_id="b"))  # a's ack went missing
        generation_of(link).end("display")

        link.close()  # nobody reads this dial: the closer drains it, then settles

        (death,) = deaths_of(link)
        assert death.suspects == frozenset({SceneId("a"), SceneId("b")})

    def test_the_drain_stops_at_the_first_reply_it_cannot_route(
        self, display: Display
    ) -> None:
        link = _linked(display, listening=False)
        writer_of(link).send_scene(_scene("a"))
        writer_of(link).send_scene(_scene("b"))
        display.peer.send(AckMessage(scene_id="b"), AckMessage(scene_id="a"))
        generation_of(link).end("display")

        link.close()

        (death,) = deaths_of(link)  # reading on would match a's ack to the wrong entry
        assert death.suspects == frozenset({SceneId("a"), SceneId("b")})

    def test_a_reply_that_fails_to_route_ends_the_drain(self, display: Display) -> None:
        generation = _generation(display)
        display.peer.send(PongMessage(ts=1.0), PongMessage(ts=2.0))
        seen: list[float] = []

        def route(_generation: DialGeneration, msg: Message) -> None:
            assert isinstance(msg, PongMessage)
            seen.append(msg.ts or 0.0)
            if msg.ts == 1.0:
                raise ValueError("a pong nobody was waiting for")

        DialDrain(route).run(generation)

        assert seen == [1.0]  # a reply that cannot be routed ends the drain


class TestACutShortDrainSaysSo:
    def test_an_end_of_file_class_error_is_logged_at_debug_with_the_endpoint(
        self,
        display: Display,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        generation = _generation(display)

        def reset(*_: object) -> object:
            raise ConnectionResetError("reset")

        monkeypatch.setattr(select, "select", reset)
        with caplog.at_level(logging.DEBUG):
            assert generation.drain().ended

        (record,) = [r for r in caplog.records if "cut short" in r.getMessage()]
        assert record.levelno == logging.DEBUG
        assert generation.endpoint in record.getMessage()
        assert "reset" in record.getMessage()

    def test_any_other_error_is_logged_as_a_warning(
        self,
        display: Display,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        generation = _generation(display)

        def closed(*_: object) -> object:
            raise ValueError("file descriptor cannot be a negative integer")

        monkeypatch.setattr(select, "select", closed)
        with caplog.at_level(logging.DEBUG):
            assert generation.drain().ended

        (record,) = [r for r in caplog.records if "cut short" in r.getMessage()]
        assert record.levelno == logging.WARNING
        assert generation.endpoint in record.getMessage()


class TestTheDrainClaimsCompletenessForSameHostSocketsOnly:
    def test_the_contract_is_stated_where_the_drain_is_defined(self) -> None:
        text = " ".join((dial_drain.__doc__ or "").split())

        assert "holds for a same-host socket only" in text
        assert "nothing here claims it is" in text
