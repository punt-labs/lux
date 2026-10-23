"""InboundRouter -- where a message the display sent back goes."""

from __future__ import annotations

import logging
import queue
import threading

import pytest

from punt_lux.domain.hub.connection_closed import ConnectionClosedError
from punt_lux.domain.hub.inbound_router import InboundRouter
from punt_lux.domain.hub.interaction_handlers import InteractionHandlers
from punt_lux.polled_event import PolledEvent
from punt_lux.protocol import (
    AckMessage,
    HubManifestMessage,
    ObserverMessage,
    PongMessage,
    QueryResponse,
    RemoteEventHandlerInvocation,
)


class _Alive:
    """A listener that is running."""

    @property
    def alive(self) -> bool:
        return True


class _Dead:
    """A listener that has exited."""

    @property
    def alive(self) -> bool:
        return False


def _click(
    element_id: str = "b1", action: str = "click"
) -> RemoteEventHandlerInvocation:
    return RemoteEventHandlerInvocation(element_id=element_id, action=action)


class TestInteractions:
    def test_an_interaction_is_answered_by_the_handlers_it_was_given(self) -> None:
        handlers = InteractionHandlers()
        seen: list[str] = []
        handlers.set_fallback(lambda m: seen.append(m.action))

        InboundRouter(handlers).route(_click())

        assert seen == ["click"]

    def test_an_interaction_is_never_queued_as_an_event(self) -> None:
        router = InboundRouter(InteractionHandlers())

        router.route(_click())

        with pytest.raises(queue.Empty):
            router.next_event(0.01)


class TestEvents:
    def test_an_observer_message_queues_as_a_polled_event(self) -> None:
        router = InboundRouter(InteractionHandlers())

        router.route(ObserverMessage(topic="t", payload={"k": 1}))

        assert router.next_event(0.1) == PolledEvent(topic="t", payload={"k": 1})

    def test_waiting_for_an_event_that_never_comes_raises_empty(self) -> None:
        with pytest.raises(queue.Empty):
            InboundRouter(InteractionHandlers()).next_event(0.01)

    def test_reset_discards_events_queued_before_it(self) -> None:
        router = InboundRouter(InteractionHandlers())
        router.route(ObserverMessage(topic="t", payload={}))

        router.reset()

        with pytest.raises(queue.Empty):
            router.next_event(0.01)


class TestReplies:
    def test_an_ack_is_handed_to_the_caller_waiting_for_one(self) -> None:
        router = InboundRouter(InteractionHandlers())
        ack = AckMessage(scene_id="s1")

        router.route(ack)

        assert router.next_reply(AckMessage, 0.1, _Alive()) == ack

    def test_a_pong_and_a_query_response_are_kept_apart(self) -> None:
        router = InboundRouter(InteractionHandlers())
        pong = PongMessage(ts=1.0)
        response = QueryResponse(method="m")

        router.route(response)
        router.route(pong)

        assert router.next_reply(PongMessage, 0.1, _Alive()) == pong
        assert router.next_reply(QueryResponse, 0.1, _Alive()) == response

    def test_waiting_for_a_reply_that_never_comes_times_out_as_none(self) -> None:
        router = InboundRouter(InteractionHandlers())
        assert router.next_reply(AckMessage, 0.01, _Alive()) is None
        assert router.next_reply(PongMessage, 0.01, _Alive()) is None

    def test_reset_discards_replies_a_dying_listener_left(self) -> None:
        router = InboundRouter(InteractionHandlers())
        router.route(AckMessage(scene_id="stale"))

        router.reset()

        assert router.next_reply(AckMessage, 0.01, _Alive()) is None


class TestUnroutableMessages:
    def test_an_unhandled_kind_is_dropped_with_a_debug_log(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        router = InboundRouter(InteractionHandlers())

        with caplog.at_level(logging.DEBUG):
            router.route(HubManifestMessage(scene_ids=()))

        assert "Dropping unhandled message: HubManifestMessage" in caplog.text
        with pytest.raises(queue.Empty):
            router.next_event(0.01)


class TestResetKeepsTheEventQueue:
    def test_a_waiter_blocked_across_a_reset_still_hears_the_next_event(self) -> None:
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

        router.reset()
        router.route(ObserverMessage(topic="t", payload={"k": "after"}))
        waiter.join(timeout=5)

        assert heard == [PolledEvent(topic="t", payload={"k": "after"})]


class TestAWaiterWatchesItsListener:
    def test_a_listener_that_exited_fails_the_waiter_instead_of_timing_out(
        self,
    ) -> None:
        router = InboundRouter(InteractionHandlers())

        with pytest.raises(ConnectionClosedError, match="listener exited"):
            router.next_reply(AckMessage, 5.0, _Dead())

    def test_a_reply_already_queued_is_still_delivered_after_the_listener_exited(
        self,
    ) -> None:
        router = InboundRouter(InteractionHandlers())
        ack = AckMessage(scene_id="s")
        router.route(ack)

        assert router.next_reply(AckMessage, 5.0, _Dead()) == ack

    def test_a_typed_reply_wait_fails_the_same_way(self) -> None:
        router = InboundRouter(InteractionHandlers())

        with pytest.raises(ConnectionClosedError):
            router.next_reply(PongMessage, 5.0, _Dead())

    def test_a_live_listener_with_nothing_to_say_times_out_quietly(self) -> None:
        router = InboundRouter(InteractionHandlers())

        assert router.next_reply(AckMessage, 0.05, _Alive()) is None
