"""MCP subscribe / publish tool surface — per-session topic scoping end-to-end."""

from __future__ import annotations

import pytest

from punt_lux.domain.hub import hub
from punt_lux.domain.ids import ConnectionId, Topic
from punt_lux.tools.server import _session_key
from punt_lux.tools.subscribe_tools import (
    drain_inbox,
    publish,
    subscribe,
    unsubscribe,
)


@pytest.fixture
def isolated_session() -> object:
    """Use a unique session key per test and clean up Hub state on exit."""

    class _Session:
        def __init__(self, key: str) -> None:
            self.key = key
            self._token: object = None

        def __enter__(self) -> str:
            self._token = _session_key.set(self.key)
            return self.key

        def __exit__(self, *_: object) -> None:
            hub.on_disconnect(ConnectionId(self.key))
            assert self._token is not None
            _session_key.reset(self._token)  # type: ignore[arg-type]

    return _Session


def test_subscribe_returns_subscribed_acknowledgement(isolated_session: type) -> None:
    with isolated_session("s-sub-ack") as _:
        result = subscribe("work.saved")
    assert result == "subscribed:work.saved"


def test_publish_with_no_subscribers_returns_zero(isolated_session: type) -> None:
    with isolated_session("s-pub-empty") as _:
        result = publish("ghost.topic", {})
    assert result == "delivered:0"


def test_subscribe_then_publish_delivers_one(isolated_session: type) -> None:
    with isolated_session("s-pub-deliver") as session_key:
        subscribe("work.saved")
        result = publish("work.saved", {"id": "save_btn"})
        inbox = drain_inbox(ConnectionId(session_key))
    assert result == "delivered:1"
    assert len(inbox) == 1
    assert inbox[0].topic == "work.saved"
    assert inbox[0].payload == {"id": "save_btn"}


def test_publish_scoped_to_caller_does_not_leak_to_other_sessions(
    isolated_session: type,
) -> None:
    # Subscribe under session A.
    with isolated_session("s-leak-a") as _:
        subscribe("shared.name")
        # Switch to session B and publish on the same topic name.
        with isolated_session("s-leak-b") as b_key:
            published = publish("shared.name", {"k": "v"})
            b_inbox = drain_inbox(ConnectionId(b_key))
        a_inbox = drain_inbox(ConnectionId("s-leak-a"))
    assert published == "delivered:0"
    assert a_inbox == ()  # A's subscriber never received B's publish
    assert b_inbox == ()  # B had no subscribers of its own


def test_unsubscribe_drops_subsequent_publishes(isolated_session: type) -> None:
    with isolated_session("s-unsub") as session_key:
        subscribe("work.saved")
        unsubscribe("work.saved")
        result = publish("work.saved", {"k": 1})
        inbox = drain_inbox(ConnectionId(session_key))
    assert result == "delivered:0"
    assert inbox == ()


def test_publish_without_explicit_subscribe_is_noop(isolated_session: type) -> None:
    """Implicit declaration on publish; with no subscribers nothing is delivered."""
    with isolated_session("s-implicit") as session_key:
        result = publish("new.topic", {"id": 1})
        inbox = drain_inbox(ConnectionId(session_key))
    assert result == "delivered:0"
    assert inbox == ()


def test_topic_set_records_active_subscription(isolated_session: type) -> None:
    with isolated_session("s-topics") as session_key:
        subscribe("a")
        subscribe("b")
        topics = hub.topics_for(ConnectionId(session_key))
    assert topics == frozenset({Topic("a"), Topic("b")})
