"""A replica lives exactly as long as an element names it (lifecycle I6)."""

from __future__ import annotations

from pathlib import Path

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
    sent: list[Frame] = []
    pool = _pool()
    session = pool.get("t1", "")
    session._channel = 7
    pool._channels[7] = session
    pool._connection = object()  # type: ignore[assignment]
    pool.send = sent.append  # type: ignore[method-assign,assignment]
    pool.retain_only(set())
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

    def __init__(self) -> None:
        self.queued: list[Frame] = []
        self.pumps = 0

    def queue(self, frame: Frame) -> None:
        self.queued.append(frame)

    def pump(self, budget_s: float) -> list[Frame]:
        self.pumps += 1
        return []


def test_a_late_attach_reply_for_a_released_replica_closes_its_channel() -> None:
    pool = _pool()
    connection = _FakeConnection()
    pool._connection = connection  # type: ignore[assignment]
    pool._requests._ready = True
    session = pool.get("gone", "")
    request_id = next(iter(pool._requests._pending))
    pool.retain_only(set())
    reply = ReplyCodec.encode(SuccessReply(request_id, {"channel": 9}))
    pool._receive(Frame(0, FrameKind.DATA, reply))
    assert session.phase is RemotePhase.CLOSED
    assert Frame(9, FrameKind.CLOSE, b"") in connection.queued
    assert 9 not in pool._channels


def test_releasing_the_last_terminal_still_flushes_its_close() -> None:
    pool = _pool()
    connection = _FakeConnection()
    session = pool.get("t1", "")
    session._channel = 7
    pool._channels[7] = session
    pool._connection = connection  # type: ignore[assignment]
    pool.retain_only(set())
    pool.pump()
    assert Frame(7, FrameKind.CLOSE, b"") in connection.queued
    assert connection.pumps == 1
