"""PubSubOperations against the real Hub and session inbox."""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING, cast, final

import pytest

from punt_lux.domain.hub import hub, hub_display
from punt_lux.domain.hub.hub import Hub
from punt_lux.domain.hub.hub_display import HubDisplay
from punt_lux.domain.hub.hub_factory import hub_element_factory
from punt_lux.domain.hub.inbox import (
    drop_session,
    ensure_writer,
    inbox_depth_for,
    next_event,
)
from punt_lux.domain.ids import ConnectionId, ElementId, SceneId
from punt_lux.domain.update import AddElement
from punt_lux.operations import PublishRequest
from punt_lux.operations.ports import HubPorts
from punt_lux.operations.pubsub import PubSubOperations
from punt_lux.operations.scope import Scope
from punt_lux.protocol.elements.text import TextElement
from punt_lux.protocol.messages.observer import ObserverMessage

if TYPE_CHECKING:
    from punt_lux.operations.display_port import DisplayPort
    from punt_lux.operations.ports import EnsureWriter, NextEvent


class _ForbiddenDisplayPort:
    """A DisplayPort that fails the test if pubsub ever reaches around to it."""

    def query(self, method: str, params: object) -> object:
        msg = f"PubSub reached around to the display: query({method!r})"
        raise AssertionError(msg)

    def ping(self, wait: float | None) -> object:
        msg = f"PubSub reached around to the display: ping({wait!r})"
        raise AssertionError(msg)


def _ports(
    ensure_writer_fn: EnsureWriter = ensure_writer,
    next_event_fn: NextEvent = next_event,
) -> HubPorts:
    """The one Hub-ports collaborator pubsub needs, with the rest stubbed off."""
    return HubPorts(
        element_factory=hub_element_factory,
        ensure_writer=ensure_writer_fn,
        next_event=next_event_fn,
        inbox_depth=inbox_depth_for,
        display_port=cast("DisplayPort", _ForbiddenDisplayPort()),
    )


def _ops() -> PubSubOperations:
    return PubSubOperations(hub, hub_display.clients, _ports())


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

    ops = PubSubOperations(hub, hub_display.clients, _ports(next_event_fn=_record))
    result = ops.receive(scope=scope)
    assert result.event is None
    assert seen == [0.0]


@final
class _Clock:
    """A hand-advanced monotonic clock, so lease expiry is deterministic."""

    def __init__(self, now: float = 0.0) -> None:
        self._now = now

    def __call__(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


def _no_event(_connection_id: ConnectionId, _timeout: float) -> ObserverMessage | None:
    return None


def test_a_pubsub_only_client_keeps_its_scene_ownership_past_its_ttl() -> None:
    """A client that shows once then only unsubscribes must not self-reap.

    Every pubsub operation is authenticated, connection-scoped contact --
    unsubscribe included, even though it is the one call here with no
    writer to touch. Advancing the clock past the lease and running the
    reap sweep between calls mirrors the background timer ticking while
    the client sits between two ordinary unsubscribe calls.
    """
    clock = _Clock()
    display = HubDisplay(clock)
    owner = ConnectionId("pubsub-only")
    display.register_client(owner)
    scene_id = SceneId("pubsub-scene")
    display.apply(
        owner,
        AddElement(
            scene_id=scene_id, element=TextElement(id="t", content="x"), parent_id=None
        ),
    )
    ops = PubSubOperations(Hub(), display.clients, _ports(lambda _c: None, _no_event))

    for _ in range(3):
        clock.advance(1801.0)  # past the 1800s unidentified-session lease
        ops.unsubscribe("some.topic", scope=Scope(owner))
        assert display.reap_lapsed_leases() == frozenset()

    assert display.is_client(owner)
    assert display.owner_of(scene_id, ElementId("t")) == owner
