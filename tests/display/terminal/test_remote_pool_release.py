"""A replica lives exactly as long as an element names it (lifecycle I6)."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("pyghostty")
pytest.importorskip("imgui_bundle")

from punt_lux.display.terminal.remote_phase import RemotePhase
from punt_lux.display.terminal.remote_pool import RemotePool
from punt_lux.protocol.pty.frames import Frame, FrameKind


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
