"""Watchers receive created and ended events; one that overflows is dropped."""

from __future__ import annotations

import pytest

pytest.importorskip("pyghostty")

from punt_lux.pty.session_watchers import SessionWatchers
from punt_lux.wire.stream.session_events import SessionEvent
from tests.pty.peer_link import PeerLink


def test_a_watcher_receives_events_in_order() -> None:
    watchers, link = SessionWatchers(), PeerLink()
    watchers.subscribe(link.peer)
    watchers.publish(SessionEvent("created", "t0.1", "work"))
    watchers.publish(SessionEvent("ended", "t0.1", "work"))
    watchers.drain()
    assert PeerLink.events(link.received()) == [
        SessionEvent("created", "t0.1", "work"),
        SessionEvent("ended", "t0.1", "work"),
    ]


def test_every_watcher_receives_every_event() -> None:
    watchers, first, second = SessionWatchers(), PeerLink(), PeerLink()
    watchers.subscribe(first.peer)
    watchers.subscribe(second.peer)
    watchers.publish(SessionEvent("created", "t0.1", "work"))
    watchers.drain()
    assert len(PeerLink.events(first.received())) == 1
    assert len(PeerLink.events(second.received())) == 1


def test_a_connection_cannot_watch_twice() -> None:
    watchers, link = SessionWatchers(), PeerLink()
    watchers.subscribe(link.peer)
    with pytest.raises(ValueError, match="already watching"):
        watchers.subscribe(link.peer)


def test_a_watcher_that_overflows_its_bounded_queue_is_dropped() -> None:
    watchers, link = SessionWatchers(limit=2), PeerLink()
    watchers.subscribe(link.peer)
    for number in range(3):
        watchers.publish(SessionEvent("created", f"t0.{number}", "x"))
    assert len(watchers) == 0
    assert link.peer.closed


def test_an_overflowed_watcher_receives_nothing_more() -> None:
    watchers, slow, healthy = SessionWatchers(limit=2), PeerLink(), PeerLink()
    watchers.subscribe(slow.peer)
    for number in range(3):
        watchers.publish(SessionEvent("created", f"t0.{number}", "x"))
    watchers.subscribe(healthy.peer)
    watchers.publish(SessionEvent("ended", "t0.0", "x"))
    watchers.drain()
    assert len(PeerLink.events(healthy.received())) == 1
    assert slow.peer.closed


def test_a_detached_watcher_is_forgotten_without_closing_its_connection() -> None:
    watchers, link = SessionWatchers(), PeerLink()
    watchers.subscribe(link.peer)
    watchers.detach(link.peer)
    watchers.publish(SessionEvent("created", "t0.1", "x"))
    assert len(watchers) == 0
    assert not link.peer.closed
