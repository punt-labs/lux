"""A viewer that fell behind keeps receiving frames while output never settles.

tmux and other full-screen programs stream without pausing at parser ground
state, so a binary snapshot can never be cut. A viewer past its backlog limit
must still be resynced, from the visible screen, and a repaint that cannot be
cut at all must cost that viewer one pump, never the daemon loop.
"""

from __future__ import annotations

from punt_lux.protocol.pty.attach import AttachRequest
from punt_lux.protocol.pty.frames import FrameKind
from punt_lux.protocol.pty.replies import ReplyCodec, SuccessReply
from punt_lux.ptyd.control_dispatch import ControlDispatch
from punt_lux.ptyd.output import SessionSnapshot
from punt_lux.ptyd.stream_output import StreamPublisher
from punt_lux.ptyd.viewers import Binding, ViewerBindings
from tests.ptyd.stream_fakes import IDLE, MidSequenceSession, QueuedCore, RecordingPeer

OVERFLOW = b"x" * (8 * 1024 * 1024)
PARTIAL_CSI = b"\x1b[1"


def _attached(bindings: ViewerBindings, name: str) -> tuple[RecordingPeer, Binding]:
    peer = RecordingPeer()
    binding = bindings.add(peer, name, 80, 24)  # type: ignore[arg-type]  # fake peer
    empty = SessionSnapshot(name, 0, 80, 24, "test", b"")
    binding.flow.prepare(empty, IDLE, initial=True)
    binding.flow.drain()
    return peer, binding


def test_lagged_viewer_is_not_starved_by_a_program_that_never_settles() -> None:
    session = MidSequenceSession("tmux")
    core = QueuedCore(session)
    bindings = ViewerBindings()
    peer, binding = _attached(bindings, "tmux")
    publisher = StreamPublisher(core, bindings)  # type: ignore[arg-type]  # fake core

    core.enqueue("tmux", OVERFLOW)
    publisher.pump()
    for _ in range(50):
        core.enqueue("tmux", PARTIAL_CSI)
        publisher.pump()

    kinds = [frame.kind for frame in peer.frames]
    assert FrameKind.SNAPSHOT_START in kinds
    assert not binding.flow.wants_repaint


def test_first_attach_to_a_program_that_never_settles_gets_a_screen() -> None:
    session = MidSequenceSession("tmux")
    core = QueuedCore(session)
    bindings = ViewerBindings()
    peer = RecordingPeer()
    dispatch = ControlDispatch(core, bindings)  # type: ignore[arg-type]  # fake core

    dispatch.execute(peer, AttachRequest(1, "tmux", cols=80, rows=24))  # type: ignore[arg-type]  # fake peer

    assert not peer.closed
    reply = ReplyCodec.decode(peer.frames[0].payload)
    assert isinstance(reply, SuccessReply)
    assert reply.result["format"] == "vt"


def test_unrepresentable_repaint_costs_one_viewer_a_pump_not_the_loop() -> None:
    broken = MidSequenceSession("broken", visible_fails=True)
    healthy = MidSequenceSession("healthy")
    core = QueuedCore(broken, healthy)
    bindings = ViewerBindings()
    broken_peer, broken_binding = _attached(bindings, "broken")
    healthy_peer, _ = _attached(bindings, "healthy")
    publisher = StreamPublisher(core, bindings)  # type: ignore[arg-type]  # fake core

    core.enqueue("broken", OVERFLOW)
    core.enqueue("healthy", OVERFLOW)
    publisher.pump()
    publisher.pump()

    assert broken_binding.flow.wants_repaint
    assert not broken_peer.frames
    assert FrameKind.SNAPSHOT_START in [frame.kind for frame in healthy_peer.frames]
    assert not broken_peer.closed


def test_resize_with_an_unrepresentable_repaint_defers_to_the_next_pump() -> None:
    broken = MidSequenceSession("broken", visible_fails=True)
    core = QueuedCore(broken)
    bindings = ViewerBindings()
    peer, binding = _attached(bindings, "broken")
    publisher = StreamPublisher(core, bindings)  # type: ignore[arg-type]  # fake core

    publisher.resize("broken", 100, 30)
    publisher.pump()

    assert binding.flow.wants_repaint
    assert not peer.frames
    assert not peer.closed
