"""Per-viewer credit and repaint ordering, independent of sockets/PTYs."""

from __future__ import annotations

import pytest

from punt_lux.protocol.pty.frames import FrameKind
from punt_lux.ptyd.credit import CreditWindow
from punt_lux.ptyd.viewer_flow import ViewerFlow
from punt_lux.terminal.output import SessionSnapshot

WINDOW = 256 * 1024
DESCRIPTION: dict[str, object] = {"ended": False, "exit_code": None}


def checkpoint(data: bytes) -> SessionSnapshot:
    return SessionSnapshot("shell", 0, 80, 24, "test", data)


def test_credit_and_inflight_always_sum_to_capacity() -> None:
    credit = CreditWindow(10)
    credit.send(7)
    assert credit.available == 3 and credit.inflight == 7
    with pytest.raises(ValueError):
        credit.send(4)
    credit.acknowledge(3)
    assert credit.available + credit.inflight == 10
    with pytest.raises(ValueError):
        credit.acknowledge(5)


def test_large_snapshot_progresses_with_partial_acks() -> None:
    flow = ViewerFlow(1)
    flow.prepare(checkpoint(b"s" * 300_000), DESCRIPTION, initial=True)
    first = flow.drain()
    assert sum(len(frame.payload) for frame in first) == WINDOW
    assert all(frame.kind is FrameKind.SNAPSHOT for frame in first)
    assert flow.drain() == []
    flow.acknowledge(64 * 1024)
    second = flow.drain()
    assert sum(len(frame.payload) for frame in second) == 300_000 - WINDOW


def test_repaint_keeps_old_inflight_debt() -> None:
    flow = ViewerFlow(1, lag_limit=8)
    flow.prepare(checkpoint(b"s" * 10_000), DESCRIPTION, initial=True)
    flow.drain()
    flow.append(b"a" * 6)
    flow.append(b"b" * 6)
    assert flow.lag_bytes == 0 and flow.wants_repaint
    flow.prepare(checkpoint(b"new"), DESCRIPTION)
    assert flow.inflight == 10_000
    reset = flow.drain()
    assert reset[0].kind is FrameKind.SNAPSHOT_START
    assert reset[1].kind is FrameKind.SNAPSHOT
    assert flow.inflight == 10_003
    flow.acknowledge(10_000)
    flow.acknowledge(3)
    with pytest.raises(ValueError):
        flow.acknowledge(1)


def test_flood_during_snapshot_does_not_restart_incomplete_transfer() -> None:
    flow = ViewerFlow(1, lag_limit=8)
    flow.prepare(checkpoint(b"s" * 300_000), DESCRIPTION, initial=True)
    flow.drain()
    flow.append(b"x" * 9)
    assert not flow.wants_repaint
    flow.acknowledge(64 * 1024)
    assert all(frame.kind is FrameKind.SNAPSHOT for frame in flow.drain())
    assert flow.wants_repaint


def test_exit_close_follows_all_queued_bytes() -> None:
    flow = ViewerFlow(1)
    flow.prepare(checkpoint(b"snap"), DESCRIPTION, initial=True)
    flow.append(b"tail")
    flow.finish("exited", 7)
    frames = flow.drain()
    assert [frame.kind for frame in frames] == [
        FrameKind.SNAPSHOT,
        FrameKind.DATA,
        FrameKind.CLOSE,
    ]
    assert flow.inflight == 8
    assert flow.drain() == []
    flow.acknowledge(8)
