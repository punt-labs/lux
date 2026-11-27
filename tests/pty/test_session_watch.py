"""A watch connection keeps events that arrive mid-request and reports its own loss."""

from __future__ import annotations

import socket

import pytest

from punt_lux.pty.daemon_exchange import RetryableRefusalError, SessionRefusedError
from punt_lux.pty.peer import Peer
from punt_lux.pty.session_watch import SessionWatch
from punt_lux.wire.stream.frames import Frame, FrameKind
from punt_lux.wire.stream.replies import FailureReply, ReplyCodec, SuccessReply
from punt_lux.wire.stream.session_events import SessionEvent


def _pair() -> tuple[SessionWatch, socket.socket]:
    ours, theirs = socket.socketpair()
    return SessionWatch(Peer(ours)), theirs


def _send(sock: socket.socket, payload: bytes) -> None:
    sock.sendall(Frame(0, FrameKind.DATA, payload).encode())


def _listing(*rows: tuple[str, str]) -> bytes:
    sessions = [{"session": s, "label": n, "state": "running"} for s, n in rows]
    return ReplyCodec.encode(SuccessReply(2, {"sessions": sessions}))


def test_events_that_precede_the_list_reply_are_kept_in_order() -> None:
    watch, daemon = _pair()
    try:
        _send(daemon, SessionEvent("created", "t0.2", "b").encode())
        _send(daemon, SessionEvent("ended", "t0.1", "a").encode())
        _send(daemon, _listing(("t0.1", "a")))
        assert dict(watch.listing().running) == {"t0.1": "a"}
        assert [e.kind for e in watch.drain()] == ["created", "ended"]
    finally:
        watch.close()
        daemon.close()


def test_an_event_in_the_same_read_as_the_reply_is_not_lost() -> None:
    watch, daemon = _pair()
    try:
        frames = Frame(0, FrameKind.DATA, _listing()).encode()
        frames += Frame(
            0, FrameKind.DATA, SessionEvent("created", "t0.3", "c").encode()
        ).encode()
        daemon.sendall(frames)
        watch.listing()
        assert watch.drain() == [SessionEvent("created", "t0.3", "c")]
    finally:
        watch.close()
        daemon.close()


def test_a_dropped_watcher_is_a_lost_connection() -> None:
    watch, daemon = _pair()
    daemon.close()
    try:
        with pytest.raises(ConnectionError):
            watch.events(1.0)
    finally:
        watch.close()


def test_an_unreadable_message_is_a_retryable_refusal() -> None:
    watch, daemon = _pair()
    try:
        _send(daemon, b"not json")
        with pytest.raises(RetryableRefusalError):
            watch.events(1.0)
    finally:
        watch.close()
        daemon.close()


def test_a_refused_list_names_the_daemon_reason() -> None:
    watch, daemon = _pair()
    try:
        _send(daemon, ReplyCodec.encode(FailureReply(2, "not ready")))
        with pytest.raises(SessionRefusedError, match="not ready"):
            watch.listing()
    finally:
        watch.close()
        daemon.close()


def test_a_quiet_watch_returns_no_events_at_the_timeout() -> None:
    watch, daemon = _pair()
    try:
        assert watch.events(0.05) == []
    finally:
        watch.close()
        daemon.close()
