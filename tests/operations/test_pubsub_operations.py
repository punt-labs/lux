"""PubSubOperations against the real Hub and session inbox."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from punt_lux.domain.hub import hub
from punt_lux.domain.hub.inbox import drop_session, ensure_writer, next_event
from punt_lux.domain.ids import ConnectionId
from punt_lux.operations import PublishRequest
from punt_lux.operations.pubsub import PubSubOperations
from punt_lux.operations.scope import Scope


def _ops() -> PubSubOperations:
    return PubSubOperations(hub, ensure_writer, next_event)


@pytest.fixture
def scope() -> Iterator[Scope]:
    connection = ConnectionId("anchor-pubsub")
    yield Scope(connection)
    hub.on_disconnect(connection)
    drop_session(connection)


def test_subscribe_publish_receive_roundtrip(scope: Scope) -> None:
    ops = _ops()
    assert ops.subscribe("work.saved", scope=scope).topic == "work.saved"

    published = ops.publish(
        "work.saved", PublishRequest(payload={"id": "b1"}), scope=scope
    )
    assert published.delivered == 1

    received = ops.receive(scope=scope)
    assert received.event is not None
    assert received.event.topic == "work.saved"
    assert received.event.payload == {"id": "b1"}

    assert ops.receive(scope=scope).event is None


def test_publish_with_no_subscribers_delivers_zero(scope: Scope) -> None:
    published = _ops().publish("no.one", PublishRequest(), scope=scope)
    assert published.delivered == 0


def test_unsubscribe_without_a_writer_is_a_noop(scope: Scope) -> None:
    result = _ops().unsubscribe("ghost", scope=scope)
    assert result.topic == "ghost"


def test_receive_drains_without_blocking(scope: Scope) -> None:
    """recv passes timeout 0.0 so it takes what is queued now, never blocks."""
    seen: list[float] = []

    def _record(_connection_id: ConnectionId, timeout: float) -> None:
        seen.append(timeout)
        return

    result = PubSubOperations(hub, ensure_writer, _record).receive(scope=scope)
    assert result.event is None
    assert seen == [0.0]
