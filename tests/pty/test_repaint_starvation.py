"""A viewer that fell behind keeps receiving frames while output never settles.

tmux and other full-screen programs stream without pausing at parser ground
state, so a binary snapshot can never be cut. A viewer past its backlog limit
must still be resynced, and a viewer whose repaint cannot be cut at all must
cost the daemon neither its loop nor an unbounded retry.
"""

from __future__ import annotations

import json
import logging
from typing import cast

import pytest

from punt_lux.pty.control_dispatch import ControlDispatch
from punt_lux.pty.control_failures import ControlFailures
from punt_lux.pty.stream_output import StreamPublisher
from punt_lux.pty.viewers import Binding, ViewerBindings
from punt_lux.terminal.output import SessionSnapshot
from punt_lux.terminal.snapshot import SnapshotError
from punt_lux.wire.stream.attach import AttachRequest
from punt_lux.wire.stream.frames import Frame, FrameKind
from punt_lux.wire.stream.replies import FailureReply, ReplyCodec, SuccessReply
from tests.pty.stream_fakes import (
    IDLE,
    MidSequenceSession,
    QueuedCore,
    RecordingPeer,
)

OVERFLOW = b"x" * (8 * 1024 * 1024)
PARTIAL_CSI = b"\x1b[1"
UNCUTTABLE = SnapshotError("formatted screen exceeds the supported size")


def _attached(bindings: ViewerBindings, name: str) -> tuple[RecordingPeer, Binding]:
    peer = RecordingPeer()
    binding = bindings.add(peer, name, 80, 24)  # type: ignore[arg-type]  # fake peer
    empty = SessionSnapshot(name, 0, 80, 24, "test", b"")
    binding.flow.prepare(empty, IDLE, initial=True)
    binding.flow.drain()
    return peer, binding


def _publisher(core: QueuedCore, bindings: ViewerBindings) -> StreamPublisher:
    return StreamPublisher(core, bindings)  # type: ignore[arg-type]  # fake core


def _close_reasons(peer: RecordingPeer) -> list[str]:
    return [
        cast("dict[str, str]", json.loads(frame.payload))["reason"]
        for frame in peer.frames
        if frame.kind is FrameKind.CLOSE
    ]


def _reply(frame: Frame) -> SuccessReply | FailureReply:
    return ReplyCodec.decode(frame.payload)


def test_lagged_viewer_is_not_starved_by_a_program_that_never_settles() -> None:
    session = MidSequenceSession("tmux")
    core = QueuedCore(session)
    bindings = ViewerBindings()
    peer, _ = _attached(bindings, "tmux")
    publisher = _publisher(core, bindings)

    core.enqueue("tmux", OVERFLOW)
    publisher.pump()
    for _ in range(50):
        core.enqueue("tmux", PARTIAL_CSI)
        publisher.pump()

    starts = [f for f in peer.frames if f.kind is FrameKind.SNAPSHOT_START]
    assert starts
    # The program keeps moving, so the screen-only viewer keeps being repainted
    # rather than resuming raw output from a position its parser cannot use.
    assert len(starts) > 1
    assert FrameKind.DATA not in [
        f.kind for f in peer.frames[peer.frames.index(starts[0]) :]
    ]


def test_a_stuck_viewer_is_closed_with_a_reason_while_others_continue(
    caplog: pytest.LogCaptureFixture,
) -> None:
    broken = MidSequenceSession("broken", checkpoint_error=UNCUTTABLE)
    healthy = MidSequenceSession("healthy")
    core = QueuedCore(broken, healthy)
    bindings = ViewerBindings()
    broken_peer, broken_binding = _attached(bindings, "broken")
    healthy_peer, _ = _attached(bindings, "healthy")
    publisher = _publisher(core, bindings)

    core.enqueue("broken", OVERFLOW)
    core.enqueue("healthy", OVERFLOW)
    with caplog.at_level(logging.WARNING, logger="punt_lux.pty.stream_output"):
        publisher.pump()
        armed = broken_binding.flow.wants_repaint
        assert armed
        assert not broken_peer.frames
        for _ in range(20):
            publisher.pump()
        calls = broken.checkpoint_calls
        for _ in range(20):
            publisher.pump()

    assert not broken_binding.flow.wants_repaint
    (reason,) = _close_reasons(broken_peer)
    assert reason.startswith("terminal repaint failed: binary: ")
    assert str(UNCUTTABLE) in reason
    assert broken.checkpoint_calls == calls < 10
    assert not broken_peer.closed
    assert FrameKind.SNAPSHOT_START in [frame.kind for frame in healthy_peer.frames]
    stuck = [r for r in caplog.records if "broken" in r.getMessage()]
    assert 1 <= len(stuck) <= 2
    assert "exceeds the supported size" in stuck[0].getMessage()


@pytest.mark.parametrize("error", [RuntimeError("terminal session is failed")])
def test_a_failing_session_finishes_that_viewer_and_the_loop_continues(
    error: Exception,
) -> None:
    failed = MidSequenceSession("failed", checkpoint_error=error)
    healthy = MidSequenceSession("healthy")
    core = QueuedCore(failed, healthy)
    bindings = ViewerBindings()
    failed_peer, _ = _attached(bindings, "failed")
    healthy_peer, _ = _attached(bindings, "healthy")
    publisher = _publisher(core, bindings)

    core.enqueue("failed", OVERFLOW)
    core.enqueue("healthy", OVERFLOW)
    publisher.pump()

    assert _close_reasons(failed_peer) == ["terminal session is failed"]
    assert FrameKind.SNAPSHOT_START in [frame.kind for frame in healthy_peer.frames]


def test_a_session_removed_while_its_viewer_repaints_finishes_only_that_viewer() -> (
    None
):
    gone = MidSequenceSession("gone")
    healthy = MidSequenceSession("healthy")
    core = QueuedCore(gone, healthy)
    bindings = ViewerBindings()
    gone_peer, gone_binding = _attached(bindings, "gone")
    healthy_peer, _ = _attached(bindings, "healthy")
    publisher = _publisher(core, bindings)

    gone_binding.flow.request_repaint()
    core.drop("gone")
    core.enqueue("healthy", OVERFLOW)
    publisher.pump()

    assert _close_reasons(gone_peer) == ["unknown terminal session gone"]
    assert FrameKind.SNAPSHOT_START in [frame.kind for frame in healthy_peer.frames]


def test_resize_to_the_size_the_core_already_has_arms_no_repaint() -> None:
    session = MidSequenceSession("tmux")
    core = QueuedCore(session)
    bindings = ViewerBindings()
    _, binding = _attached(bindings, "tmux")
    publisher = _publisher(core, bindings)

    publisher.resize("tmux", 80, 24)
    assert not binding.flow.wants_repaint
    publisher.resize("tmux", 100, 30)
    assert binding.flow.wants_repaint


def test_a_doubly_failed_first_attach_fails_one_request_and_keeps_the_connection(
    caplog: pytest.LogCaptureFixture,
) -> None:
    broken = MidSequenceSession("broken", checkpoint_error=UNCUTTABLE)
    healthy = MidSequenceSession("healthy")
    core = QueuedCore(broken, healthy)
    bindings = ViewerBindings()
    peer = RecordingPeer()
    dispatch = ControlDispatch(core, bindings)  # type: ignore[arg-type]  # fake core

    with caplog.at_level(logging.WARNING, logger="punt_lux.pty.control_dispatch"):
        for request_id, name in ((1, "broken"), (2, "healthy")):
            ControlFailures.execute(
                dispatch,
                peer,  # type: ignore[arg-type]  # fake peer
                AttachRequest(request_id, name, cols=80, rows=24),
            )

    failure, success = (_reply(frame) for frame in peer.frames)
    assert isinstance(failure, FailureReply)
    assert failure.request_id == 1
    assert failure.retryable
    assert isinstance(success, SuccessReply)
    assert success.request_id == 2
    assert not peer.closed
    assert any("broken" in record.getMessage() for record in caplog.records)
