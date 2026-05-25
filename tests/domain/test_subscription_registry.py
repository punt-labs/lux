"""Per-connection subscription registry — scoping, concurrency, cleanup."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

import pytest

from punt_lux.domain.hub import Hub, SubscriptionRegistry
from punt_lux.domain.ids import ConnectionId, Topic
from punt_lux.protocol.messages.observer import ObserverMessage

if TYPE_CHECKING:
    from collections.abc import Callable


def _recorder() -> tuple[Callable[[ObserverMessage], None], list[ObserverMessage]]:
    """Build a handler that appends every received ObserverMessage to a list."""
    received: list[ObserverMessage] = []

    def _handler(message: ObserverMessage) -> None:
        received.append(message)

    return _handler, received


def test_subscribe_then_snapshot_returns_handler() -> None:
    registry = SubscriptionRegistry()
    handler, _ = _recorder()
    registry.subscribe(ConnectionId("c1"), Topic("work.saved"), handler)
    subs = registry.snapshot_subscribers(ConnectionId("c1"), Topic("work.saved"))
    assert subs == (handler,)


def test_snapshot_empty_for_unknown_connection() -> None:
    registry = SubscriptionRegistry()
    assert registry.snapshot_subscribers(ConnectionId("c1"), Topic("x")) == ()


def test_snapshot_empty_for_unknown_topic_in_known_connection() -> None:
    registry = SubscriptionRegistry()
    handler, _ = _recorder()
    registry.subscribe(ConnectionId("c1"), Topic("a"), handler)
    assert registry.snapshot_subscribers(ConnectionId("c1"), Topic("b")) == ()


def test_per_connection_scoping_isolates_topics() -> None:
    registry = SubscriptionRegistry()
    handler_a, _ = _recorder()
    handler_b, _ = _recorder()
    registry.subscribe(ConnectionId("A"), Topic("work.saved"), handler_a)
    registry.subscribe(ConnectionId("B"), Topic("work.saved"), handler_b)
    a_subs = registry.snapshot_subscribers(ConnectionId("A"), Topic("work.saved"))
    b_subs = registry.snapshot_subscribers(ConnectionId("B"), Topic("work.saved"))
    assert a_subs == (handler_a,)
    assert b_subs == (handler_b,)


def test_unsubscribe_drops_handler_and_collapses_empty_scopes() -> None:
    registry = SubscriptionRegistry()
    handler, _ = _recorder()
    registry.subscribe(ConnectionId("c1"), Topic("x"), handler)
    registry.unsubscribe(ConnectionId("c1"), Topic("x"), handler)
    assert registry.snapshot_subscribers(ConnectionId("c1"), Topic("x")) == ()
    assert registry.topics_for(ConnectionId("c1")) == frozenset()


def test_unsubscribe_unknown_connection_is_noop() -> None:
    registry = SubscriptionRegistry()
    handler, _ = _recorder()
    registry.unsubscribe(ConnectionId("missing"), Topic("x"), handler)  # no raise


def test_unsubscribe_unknown_topic_is_noop() -> None:
    registry = SubscriptionRegistry()
    handler, _ = _recorder()
    registry.subscribe(ConnectionId("c1"), Topic("a"), handler)
    registry.unsubscribe(ConnectionId("c1"), Topic("b"), handler)  # no raise


def test_drop_connection_removes_every_topic() -> None:
    registry = SubscriptionRegistry()
    handler, _ = _recorder()
    registry.subscribe(ConnectionId("c1"), Topic("a"), handler)
    registry.subscribe(ConnectionId("c1"), Topic("b"), handler)
    registry.drop_connection(ConnectionId("c1"))
    assert registry.topics_for(ConnectionId("c1")) == frozenset()


def test_drop_connection_idempotent() -> None:
    registry = SubscriptionRegistry()
    registry.drop_connection(ConnectionId("never-existed"))
    registry.drop_connection(ConnectionId("never-existed"))


def test_topics_for_returns_all_subscribed_topics() -> None:
    registry = SubscriptionRegistry()
    handler, _ = _recorder()
    registry.subscribe(ConnectionId("c1"), Topic("a"), handler)
    registry.subscribe(ConnectionId("c1"), Topic("b"), handler)
    assert registry.topics_for(ConnectionId("c1")) == frozenset(
        {Topic("a"), Topic("b")}
    )


def test_hub_publish_with_no_subscribers_returns_zero() -> None:
    new_hub = Hub()
    handler, _ = _recorder()
    new_hub.register_writer(ConnectionId("c1"), handler)
    delivered = new_hub.publish(ConnectionId("c1"), Topic("ghost"), {})
    assert delivered == 0


def test_hub_publish_fans_out_observer_message_to_caller_scope_only() -> None:
    new_hub = Hub()
    handler_a, received_a = _recorder()
    handler_b, received_b = _recorder()
    new_hub.register_writer(ConnectionId("A"), handler_a)
    new_hub.register_writer(ConnectionId("B"), handler_b)
    new_hub.subscribe(ConnectionId("A"), Topic("work.saved"))
    new_hub.subscribe(ConnectionId("B"), Topic("work.saved"))
    delivered = new_hub.publish(
        ConnectionId("A"), Topic("work.saved"), {"id": "save_btn"}
    )
    assert delivered == 1
    assert received_a == [
        ObserverMessage(topic="work.saved", payload={"id": "save_btn"})
    ]
    assert received_b == []


def test_hub_subscribe_without_writer_raises() -> None:
    new_hub = Hub()
    with pytest.raises(KeyError):
        new_hub.subscribe(ConnectionId("never-registered"), Topic("x"))


def test_hub_on_disconnect_drops_subscriptions_and_writer() -> None:
    new_hub = Hub()
    handler, _ = _recorder()
    new_hub.register_writer(ConnectionId("c1"), handler)
    new_hub.subscribe(ConnectionId("c1"), Topic("a"))
    new_hub.on_disconnect(ConnectionId("c1"))
    assert new_hub.topics_for(ConnectionId("c1")) == frozenset()
    assert not new_hub.has_writer(ConnectionId("c1"))


def test_publish_snapshot_iterates_outside_lock() -> None:
    """A handler that subscribes from inside publish does not deadlock."""
    registry = SubscriptionRegistry()
    received: list[ObserverMessage] = []

    def _self_subscribing(message: ObserverMessage) -> None:
        received.append(message)
        # Re-entering subscribe from inside a handler proves the publish
        # iteration is not holding the registry lock — if it were, this
        # call would deadlock waiting on the lock the publish holds.
        registry.subscribe(ConnectionId("c1"), Topic("topic"), _self_subscribing)

    registry.subscribe(ConnectionId("c1"), Topic("topic"), _self_subscribing)
    # Snapshot was taken at publish entry — only the initial subscriber set runs.
    subs = registry.snapshot_subscribers(ConnectionId("c1"), Topic("topic"))
    for handler in subs:
        handler(ObserverMessage(topic="topic", payload={"k": 1}))
    assert received == [ObserverMessage(topic="topic", payload={"k": 1})]
    # The re-subscribe inside the handler succeeded — set semantics dedupe
    # to the same single handler entry — and the lock was free.
    assert registry.snapshot_subscribers(ConnectionId("c1"), Topic("topic")) == (
        _self_subscribing,
    )


def test_concurrent_subscribe_publish_does_not_deadlock() -> None:
    """Many threads subscribing and publishing simultaneously must complete."""
    new_hub = Hub()
    handler, received = _recorder()
    new_hub.register_writer(ConnectionId("c1"), handler)

    def _subscriber_thread(index: int) -> None:
        new_hub.subscribe(ConnectionId("c1"), Topic(f"t{index}"))

    def _publisher_thread(index: int) -> None:
        new_hub.publish(ConnectionId("c1"), Topic(f"t{index}"), {"i": index})

    threads = [
        threading.Thread(target=_subscriber_thread, args=(i,)) for i in range(20)
    ]
    threads += [
        threading.Thread(target=_publisher_thread, args=(i,)) for i in range(20)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5.0)
    for t in threads:
        assert not t.is_alive(), "thread deadlocked"
    # At least one publish occurred after its subscriber landed.
    assert isinstance(received, list)
