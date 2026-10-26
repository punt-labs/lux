"""Waiting for acks is a request of its own: one at a time, and it runs held clicks."""

from __future__ import annotations

import inspect
from typing import TYPE_CHECKING

import pytest

from punt_lux.domain.hub.display_busy import DisplayBusyError
from punt_lux.domain.hub.display_connection import DisplayConnection
from punt_lux.protocol import AckMessage, RemoteEventHandlerInvocation
from tests.domain.display_double import Call, Display, until
from tests.domain.test_retire_cause import _linked, _scene
from tests.link_access import generation_of, no_reader, writer_of

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture
def display() -> Iterator[Display]:
    d = Display()
    yield d
    d.close()


class TestTwoWaitsForAcks:
    def test_the_second_is_busy_not_a_bare_runtime_error(
        self, display: Display
    ) -> None:
        link = _linked(display)
        writer_of(link).send_scene(_scene("a"))
        first = Call(lambda: link.desk.asks().await_acks(3.0))
        assert until(lambda: generation_of(link).owed_acks == 1)

        with pytest.raises(DisplayBusyError):
            link.desk.asks().await_acks(0.2)

        display.peer.send(AckMessage(scene_id="a"))
        assert first.wait()
        assert first.result is True

    def test_a_wait_with_nothing_owed_is_at_once_true(self, display: Display) -> None:
        link = _linked(display)

        assert link.desk.asks().await_acks(0.1) is True


class TestAClickHeldByAnInlineWaitForAcks:
    def test_it_runs_when_the_wait_ends(self, display: Display) -> None:
        link = _linked(display, listening=False)
        seen: list[RemoteEventHandlerInvocation] = []
        link.events.set_fallback_handler(seen.append)
        writer_of(link).send_scene(_scene("a"))
        click = RemoteEventHandlerInvocation(element_id="b", action="click")

        display.peer.send(click, AckMessage(scene_id="a"))

        assert link.desk.asks().await_acks(3.0) is True
        assert seen == [click]


class TestAConnectionNeedsToKnowWhoSettlesWhatNoReaderHolds:
    def test_the_settle_has_no_default_and_is_keyword_only(self) -> None:
        parameter = inspect.signature(DisplayConnection).parameters["settle_unread"]

        assert parameter.default is inspect.Parameter.empty
        assert parameter.kind is inspect.Parameter.KEYWORD_ONLY

    def test_a_connection_given_one_is_made(self, display: Display) -> None:
        assert DisplayConnection(display, 1.0, settle_unread=no_reader).endpoint


class TestWhoReadsADialIsTheGenerationsDecision:
    def test_the_socket_holds_no_reader_slot(self, display: Display) -> None:
        generation = generation_of(_linked(display, listening=False))

        assert "reader_slot" not in dir(generation._socket)
        assert generation.claim_reader() is True
        assert generation.has_reader is True

    def test_the_generation_names_itself_the_same_way_every_time(
        self, display: Display
    ) -> None:
        link = _linked(display)
        generation = generation_of(link)

        assert generation.ref == generation.ref
        assert link.desk.asks().dial == generation.ref
