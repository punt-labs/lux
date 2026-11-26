"""A watcher that lost events reconciles against the daemon's list (daemon side)."""

from __future__ import annotations

import pytest

pytest.importorskip("pyghostty")

from punt_lux.pty.core import SessionCore
from punt_lux.pty.dispatch import SessionDispatch
from punt_lux.terminal.snapshot import snapshot_version
from punt_lux.wire.stream.control import WIRE_VERSION
from punt_lux.wire.stream.hello import HelloRequest
from punt_lux.wire.stream.new_request import NewRequest
from punt_lux.wire.stream.replies import SuccessReply
from punt_lux.wire.stream.session_events import SessionEvent, WatchRequest
from punt_lux.wire.stream.session_requests import KillRequest, ListRequest
from tests.pty.fake_process import FakeFactory
from tests.pty.peer_link import PeerLink


def _connected(dispatch: SessionDispatch) -> PeerLink:
    link = PeerLink()
    reply = link.request(dispatch, HelloRequest(1, WIRE_VERSION, snapshot_version()))
    assert isinstance(reply, SuccessReply)
    return link


def _created_ids(link: PeerLink, dispatch: SessionDispatch, count: int) -> list[str]:
    ids: list[str] = []
    for number in range(count):
        reply = link.request(dispatch, NewRequest(10 + number))
        assert isinstance(reply, SuccessReply)
        ids.append(str(reply.result["session"]))
    return ids


def test_watch_is_acknowledged_before_any_event_is_delivered() -> None:
    core = SessionCore(FakeFactory())
    dispatch = SessionDispatch(core)
    watcher, actor = _connected(dispatch), _connected(dispatch)
    try:
        assert isinstance(watcher.request(dispatch, WatchRequest(2)), SuccessReply)
        _created_ids(actor, dispatch, 1)
        events = PeerLink.events(watcher.settled(dispatch))
        assert [e.kind for e in events] == ["created"]
    finally:
        core.close()


def test_lost_events_then_a_fresh_watch_and_list_equal_the_daemons_sessions() -> None:
    core = SessionCore(FakeFactory())
    dispatch = SessionDispatch(core)
    watcher, actor = _connected(dispatch), _connected(dispatch)
    try:
        assert isinstance(watcher.request(dispatch, WatchRequest(2)), SuccessReply)
        # Fifty creates and kills publish 100 events before the watcher drains.
        for number in range(50):
            (session,) = _created_ids(actor, dispatch, 1)
            assert isinstance(
                actor.request(dispatch, KillRequest(200 + number, session)),
                SuccessReply,
            )
        (kept,) = _created_ids(actor, dispatch, 1)
        assert watcher.peer.closed  # dropped: it must re-dial and reconcile

        redialed = _connected(dispatch)
        assert isinstance(redialed.request(dispatch, WatchRequest(2)), SuccessReply)
        listing = redialed.request(dispatch, ListRequest(3))
        assert isinstance(listing, SuccessReply)
        sessions = listing.result["sessions"]
        assert isinstance(sessions, list)
        assert [s["session"] for s in sessions] == [kept]
    finally:
        core.close()


def test_an_ended_event_names_the_label_the_session_held() -> None:
    core = SessionCore(FakeFactory())
    dispatch = SessionDispatch(core)
    watcher, actor = _connected(dispatch), _connected(dispatch)
    try:
        assert isinstance(watcher.request(dispatch, WatchRequest(2)), SuccessReply)
        reply = actor.request(dispatch, NewRequest(5, "work"))
        assert isinstance(reply, SuccessReply)
        session = str(reply.result["session"])
        actor.request(dispatch, KillRequest(6, session))
        events = PeerLink.events(watcher.settled(dispatch))
        assert events == [
            SessionEvent("created", session, "work"),
            SessionEvent("ended", session, "work"),
        ]
    finally:
        core.close()
