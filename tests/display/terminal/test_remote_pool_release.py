"""A replica lives exactly as long as an element names it (lifecycle I6)."""

from __future__ import annotations

from pathlib import Path
from typing import Self

import pytest

pytest.importorskip("pyghostty")
pytest.importorskip("imgui_bundle")

from punt_lux.display.terminal.remote import RemoteSession
from punt_lux.display.terminal.remote_phase import RemotePhase
from punt_lux.display.terminal.remote_pool import RemotePool
from punt_lux.protocol.pty.frames import Frame, FrameKind
from punt_lux.protocol.pty.replies import ReplyCodec, SuccessReply


def _pool() -> RemotePool:
    return RemotePool(Path("/nonexistent/luxd-pty.sock"))


def test_retain_only_closes_and_forgets_unnamed_replicas() -> None:
    pool = _pool()
    kept, gone = pool.get("kept", ""), pool.get("gone", "")
    pool.retain_only({"kept"})
    assert gone.phase is RemotePhase.CLOSED
    assert pool.get("kept", "") is kept


def test_readded_name_gets_a_fresh_replica() -> None:
    pool = _pool()
    first = pool.get("t1", "")
    pool.retain_only(set())
    second = pool.get("t1", "")
    assert second is not first
    assert second.phase is RemotePhase.CONNECTING


def test_failed_replica_stays_on_screen_while_its_element_is_present() -> None:
    pool = _pool()
    session = pool.get("t1", "")
    session.fail("unknown session")
    pool.retain_only({"t1"})
    assert pool.get("t1", "") is session
    assert session.phase is RemotePhase.FAILED


def test_release_closes_the_daemon_channel() -> None:
    pool, _, sent = _released_pool_with_a_live_peer()
    assert Frame(7, FrameKind.CLOSE, b"") in sent
    assert 7 not in pool._channels


def _released_pool_with_a_live_peer() -> tuple[RemotePool, RemoteSession, list[Frame]]:
    sent: list[Frame] = []
    pool = _pool()
    gone, live = pool.get("gone", ""), pool.get("live", "")
    gone._channel, live._channel = 7, 8
    pool._channels[7], pool._channels[8] = gone, live
    pool._connection = object()  # type: ignore[assignment]
    pool.send = sent.append  # type: ignore[method-assign,assignment]
    pool.retain_only({"live"})
    return pool, live, sent


@pytest.mark.parametrize("kind", [FrameKind.DATA, FrameKind.SNAPSHOT, FrameKind.CLOSE])
def test_a_late_frame_for_a_released_channel_spares_other_terminals(
    kind: FrameKind,
) -> None:
    pool, live, _ = _released_pool_with_a_live_peer()
    pool._receive(Frame(7, kind, b""))
    assert pool._channels.get(8) is live
    assert live.phase is not RemotePhase.DISCONNECTED


class _FakeConnection:
    """Records queued frames and flushes; the daemon sends nothing back."""

    _queued: list[Frame]
    _pumps: int
    _closed: bool

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._queued = []
        self._pumps = 0
        self._closed = False
        return self

    @property
    def closed(self) -> bool:
        return self._closed

    def close(self) -> None:
        self._closed = True

    @property
    def queued(self) -> list[Frame]:
        return self._queued

    @property
    def pumps(self) -> int:
        return self._pumps

    def queue(self, frame: Frame) -> None:
        self._queued.append(frame)

    def pump(self, budget_s: float) -> list[Frame]:
        self._pumps += 1
        return []


def test_a_late_attach_reply_for_a_released_replica_closes_its_channel() -> None:
    pool = _pool()
    connection = _FakeConnection()
    pool._connection = connection  # type: ignore[assignment]
    pool._requests._ready = True
    session = pool.get("gone", "")
    request_id = next(iter(pool._requests._pending))
    pool.get("live", "")
    pool.retain_only({"live"})
    reply = ReplyCodec.encode(SuccessReply(request_id, {"channel": 9}))
    pool._receive(Frame(0, FrameKind.DATA, reply))
    assert session.phase is RemotePhase.CLOSED
    assert Frame(9, FrameKind.CLOSE, b"") in connection.queued
    assert 9 not in pool._channels


def test_releasing_the_last_terminal_closes_the_idle_connection() -> None:
    """With no replica left, the socket closes: the daemon frees every viewer."""
    pool = _pool()
    connection = _FakeConnection()
    pool._connection = connection  # type: ignore[assignment]
    pool._requests._ready = True
    session = pool.get("t1", "")
    session._channel = 7
    pool._channels[7] = session
    pool.retain_only(set())
    assert connection.closed
    assert pool._connection is None
    assert not pool._released
    assert not pool._requests.ready
    assert not pool.pump()


def test_releasing_the_last_terminal_with_an_unsent_attach_sends_nothing() -> None:
    """Model trace O: ReplicaAsk, ReleaseAsked, FinalPump must not bind a viewer."""
    pool = _pool()
    connection = _FakeConnection()
    pool._connection = connection  # type: ignore[assignment]
    pool._requests._ready = True
    pool.get("t1", "")
    pool.retain_only(set())
    pool.pump()
    assert connection.closed
    assert connection.pumps == 0


def test_a_name_reopened_before_its_cancelled_reply_waits_for_it() -> None:
    """Model trace F: the reopened attach is held until the old reply is read."""
    pool = _pool()
    connection = _FakeConnection()
    pool._connection = connection  # type: ignore[assignment]
    pool._requests._ready = True
    pool.get("other", "")
    pool.get("n", "")
    old_id = max(pool._requests._pending)
    pool.retain_only({"other"})
    reopened = pool.get("n", "")
    attaches = [f for f in connection.queued if b'"session":"n"' in f.payload]
    assert len(attaches) == 1
    reply = ReplyCodec.encode(SuccessReply(old_id, {"channel": 9}))
    pool._receive(Frame(0, FrameKind.DATA, reply))
    for session in pool._requests.due():
        pool._attach(session)
    attaches = [f for f in connection.queued if b'"session":"n"' in f.payload]
    assert len(attaches) == 2
    assert reopened.phase is RemotePhase.CONNECTING


def test_data_behind_a_late_attach_reply_spares_other_terminals() -> None:
    pool = _pool()
    pool._connection = _FakeConnection()  # type: ignore[assignment]
    pool._requests._ready = True
    pool.get("gone", "")
    request_id = next(iter(pool._requests._pending))
    live = pool.get("live", "")
    live._channel = 8
    pool._channels[8] = live
    pool.retain_only({"live"})
    reply = ReplyCodec.encode(SuccessReply(request_id, {"channel": 9}))
    pool._receive(Frame(0, FrameKind.DATA, reply))
    pool._receive(Frame(9, FrameKind.SNAPSHOT, b""))
    pool._receive(Frame(9, FrameKind.DATA, b""))
    assert pool._channels.get(8) is live
    assert live.phase is not RemotePhase.DISCONNECTED
