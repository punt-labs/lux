"""DialDrain -- the last look at a dial's socket routes everything it holds, once."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import pytest

from punt_lux.domain.hub.dial_drain import DialDrain
from punt_lux.protocol import AckMessage, PongMessage, encode_message
from tests.domain.display_double import Display
from tests.domain.test_retire_cause import _linked
from tests.link_access import generation_of

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
    def test_a_route_that_raises_costs_only_its_own_message(
        self, display: Display, caplog: pytest.LogCaptureFixture
    ) -> None:
        generation = _generation(display)
        display.peer.send(AckMessage(scene_id="bad"), AckMessage(scene_id="good"))
        seen: list[str] = []

        def route(_generation: DialGeneration, msg: Message) -> None:
            assert isinstance(msg, AckMessage)
            if msg.scene_id == "bad":
                raise ValueError("this one cannot be routed")
            seen.append(msg.scene_id)

        with caplog.at_level(logging.ERROR):
            DialDrain(route).run(generation)

        assert seen == ["good"]
        assert "Drain route failed" in caplog.text

    def test_a_frame_that_cannot_be_decoded_ends_the_drain_and_says_so(
        self, display: Display, caplog: pytest.LogCaptureFixture
    ) -> None:
        generation = _generation(display)
        display.peer.send_raw(b"\x00\x00\x00\x05not-json")

        with caplog.at_level(logging.ERROR):
            routed = _routed_by_a_drain(generation)

        assert routed == []
        assert "could not be read past" in caplog.text
