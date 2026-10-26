"""InboundRouter -- where a message the display sent back goes."""

from __future__ import annotations

import logging
import queue
import socket
import threading
from typing import TYPE_CHECKING

import pytest

from punt_lux.domain.hub.dial_generation import DialEnds, DialGeneration
from punt_lux.domain.hub.handshake_outcome import HandshakeResult
from punt_lux.domain.hub.inbound_router import InboundRouter
from punt_lux.domain.hub.interaction_handlers import InteractionHandlers
from punt_lux.polled_event import PolledEvent
from punt_lux.protocol import (
    AckMessage,
    HubManifestMessage,
    ObserverMessage,
    PongMessage,
    QueryRequest,
    QueryResponse,
    ReadyMessage,
    RemoteEventHandlerInvocation,
    SceneMessage,
)

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture
def generation() -> Iterator[DialGeneration]:
    ours, theirs = socket.socketpair()
    made = DialGeneration(
        HandshakeResult(sock=ours, endpoint="pair", ready=ReadyMessage()),
        DialEnds(lambda _g, _c: True, lambda _g, _c: True),
    )
    yield made
    made.shut()
    theirs.close()


def _another() -> tuple[DialGeneration, socket.socket]:
    ours, theirs = socket.socketpair()
    return (
        DialGeneration(
            HandshakeResult(sock=ours, endpoint="other", ready=ReadyMessage()),
            DialEnds(lambda _g, _c: True, lambda _g, _c: True),
        ),
        theirs,
    )


def _click(
    element_id: str = "b1", action: str = "click"
) -> RemoteEventHandlerInvocation:
    return RemoteEventHandlerInvocation(element_id=element_id, action=action)


class TestInteractions:
    def test_an_interaction_is_answered_by_the_handlers_it_was_given(
        self, generation: DialGeneration
    ) -> None:
        handlers = InteractionHandlers()
        seen: list[str] = []
        handlers.set_fallback(lambda m: seen.append(m.action))

        InboundRouter(handlers).route(generation, _click())

        assert seen == ["click"]

    def test_an_interaction_is_never_queued_as_an_event(
        self, generation: DialGeneration
    ) -> None:
        router = InboundRouter(InteractionHandlers())

        router.route(generation, _click())

        with pytest.raises(queue.Empty):
            router.next_event(0.01)


class TestEvents:
    def test_an_observer_message_queues_as_a_polled_event(
        self, generation: DialGeneration
    ) -> None:
        router = InboundRouter(InteractionHandlers())

        router.route(generation, ObserverMessage(topic="t", payload={"k": 1}))

        assert router.next_event(0.1) == PolledEvent(topic="t", payload={"k": 1})

    def test_waiting_for_an_event_that_never_comes_raises_empty(self) -> None:
        with pytest.raises(queue.Empty):
            InboundRouter(InteractionHandlers()).next_event(0.01)

    def test_an_event_outlives_the_dial_that_carried_it(
        self, generation: DialGeneration
    ) -> None:
        router = InboundRouter(InteractionHandlers())
        router.route(generation, ObserverMessage(topic="t", payload={}))

        generation.shut()

        assert router.next_event(0.1) == PolledEvent(topic="t", payload={})

    def test_an_event_a_straggler_routes_after_its_dial_ended_is_still_delivered(
        self, generation: DialGeneration
    ) -> None:
        router = InboundRouter(InteractionHandlers())
        generation.shut()

        router.route(generation, ObserverMessage(topic="late", payload={}))

        assert router.next_event(0.1) == PolledEvent(topic="late", payload={})

    def test_a_waiter_blocked_across_a_dial_s_end_hears_the_next_event(
        self, generation: DialGeneration
    ) -> None:
        router = InboundRouter(InteractionHandlers())
        heard: list[PolledEvent] = []
        waiting = threading.Event()

        def wait() -> None:
            waiting.set()
            heard.append(router.next_event(5.0))

        waiter = threading.Thread(target=wait)
        waiter.start()
        waiting.wait(timeout=3)
        threading.Event().wait(0.1)

        generation.shut()
        router.route(generation, ObserverMessage(topic="t", payload={"k": "after"}))
        waiter.join(timeout=5)

        assert heard == [PolledEvent(topic="t", payload={"k": "after"})]


class TestReplies:
    def test_a_reply_goes_into_the_sink_of_the_generation_that_carried_it(
        self, generation: DialGeneration
    ) -> None:
        router = InboundRouter(InteractionHandlers())
        other, theirs = _another()
        try:
            mine = generation.send_ping(1.0)
            theirs_waiting = other.send_ping(1.0)

            router.route(generation, PongMessage(ts=1.0))

            assert generation.await_reply(mine, 0.0) == PongMessage(ts=1.0)
            assert other.await_reply(theirs_waiting, 0.0) is None
        finally:
            other.shut()
            theirs.close()

    def test_a_reply_from_a_retired_generation_is_dropped_not_parked(
        self, generation: DialGeneration
    ) -> None:
        router = InboundRouter(InteractionHandlers())
        generation.mark_closed("hub")  # retired: its ledger is taken

        router.route(generation, AckMessage(scene_id="late"))
        router.route(generation, PongMessage(ts=1.0))
        router.route(generation, QueryResponse(method="m"))

        assert generation.owed_acks == 0

    def test_an_ack_the_display_owes_settles_the_ledger(
        self, generation: DialGeneration
    ) -> None:
        router = InboundRouter(InteractionHandlers())
        generation.send_scene(SceneMessage(id="s1", elements=[], frame_id="s1"))
        assert generation.owed_acks == 1

        router.route(generation, AckMessage(scene_id="s1"))

        assert generation.owed_acks == 0

    def test_a_pong_and_a_query_response_are_kept_apart(
        self, generation: DialGeneration
    ) -> None:
        router = InboundRouter(InteractionHandlers())
        ping = generation.send_ping(1.0)
        query = generation.send_query(QueryRequest(method="m"))

        router.route(generation, QueryResponse(method="m"))
        router.route(generation, PongMessage(ts=1.0))

        assert generation.await_reply(ping, 0.0) == PongMessage(ts=1.0)
        assert generation.await_reply(query, 0.0) == QueryResponse(method="m")


class TestUnroutableMessages:
    def test_an_unhandled_kind_is_dropped_with_a_debug_log(
        self, generation: DialGeneration, caplog: pytest.LogCaptureFixture
    ) -> None:
        router = InboundRouter(InteractionHandlers())

        with caplog.at_level(logging.DEBUG):
            router.route(generation, HubManifestMessage(scene_ids=()))

        assert "Dropping unhandled message: HubManifestMessage" in caplog.text
        with pytest.raises(queue.Empty):
            router.next_event(0.01)
