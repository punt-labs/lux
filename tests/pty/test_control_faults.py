"""Transport-level construction/cleanup faults do not terminate other sessions."""

from __future__ import annotations

import socket
from typing import TYPE_CHECKING, Never

import pytest

pytest.importorskip("pyghostty")

from punt_lux.pty.core import SessionCore
from punt_lux.pty.peer import Peer
from punt_lux.pty.process_port import ProcessPort
from punt_lux.pty.session_spec import SessionSpec
from punt_lux.pty.stream_output import StreamPublisher
from punt_lux.pty.viewers import ViewerBindings
from punt_lux.wire.stream.attach import AttachRequest
from punt_lux.wire.stream.control import ControlCodec, KillRequest
from punt_lux.wire.stream.frames import Frame, FrameDecoder, FrameKind
from punt_lux.wire.stream.new_request import NewRequest
from punt_lux.wire.stream.replies import FailureReply, ReplyCodec
from tests.pty.fake_process import FakeFactory
from tests.pty.stream_fakes import Controls

if TYPE_CHECKING:
    from pytest import MonkeyPatch


@pytest.mark.parametrize("message", ["terminal allocation fault", ""])
@pytest.mark.parametrize("fault_type", [MemoryError, SystemExit, KeyboardInterrupt])
@pytest.mark.parametrize("refuse_cleanup", [False, True])
def test_transport_fault_boundary_preserves_other_sessions_and_operator_signals(
    monkeypatch: MonkeyPatch,
    refuse_cleanup: bool,
    fault_type: type[BaseException],
    message: str,
) -> None:
    factory = FakeFactory()
    core = SessionCore(factory)
    good_name = core.create(NewRequest(1, "good")).name
    good = factory.created[0]
    client, owned = socket.socketpair()
    client.settimeout(1)
    peer = Peer(owned)
    peer.mark_ready()
    control = Controls.input(core, ViewerBindings())

    def fail(_spec: SessionSpec, _process: ProcessPort) -> Never:
        factory.created[-1].refuse_close = refuse_cleanup
        raise fault_type(message)

    monkeypatch.setattr("punt_lux.pty.session_birth.TerminalSession", fail)
    try:
        request = NewRequest(7, "bad")
        frame = Frame(0, FrameKind.DATA, ControlCodec.encode(request))
        if fault_type is not MemoryError:
            expected = BaseExceptionGroup if refuse_cleanup else fault_type
            with pytest.raises(expected):
                control.receive(peer, frame)
            assert good.alive and good.close_calls == 0
            return
        control.receive(peer, frame)
        peer.flush()
        frames = FrameDecoder().feed(client.recv(65536))
        assert len(frames) == 1
        reply = ReplyCodec.decode(frames[0].payload)
        assert isinstance(reply, FailureReply)
        assert reply.request_id == 7
        assert reply.error
        assert reply.retryable
        assert peer.ready
        assert good.alive and good.close_calls == 0
        assert core.get(good_name).name == good_name
        if refuse_cleanup:
            pending = core.describe()[-1]
            assert pending["cleanup_pending"] is True
            assert pending["pid"] == 123
        else:
            assert len(core.describe()) == 1
    finally:
        for process in factory.created:
            process.refuse_close = False
        peer.close()
        client.close()
        core.close()


def test_kill_cleanup_failure_finishes_repaint_before_publishing_other_sessions(
    monkeypatch: MonkeyPatch,
) -> None:
    factory = FakeFactory()
    core = SessionCore(factory)
    dying_name = core.create(NewRequest(1, "dying")).name
    running_name = core.create(NewRequest(2, "running")).name
    process, running = factory.created
    process.reaped = False
    original_close = process.close
    calls = 0

    def close() -> bool:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("reap failed")
        return original_close()

    monkeypatch.setattr(process, "close", close)
    client, owned = socket.socketpair()
    client.settimeout(1)
    peer = Peer(owned)
    peer.mark_ready()
    bindings = ViewerBindings()
    binding = bindings.add(peer, dying_name, 80, 24)
    try:
        Controls.input(core, bindings).receive(
            peer,
            Frame(0, FrameKind.DATA, ControlCodec.encode(KillRequest(3, dying_name))),
        )
        assert not binding.flow.wants_repaint
        assert core.describe()[-1]["cleanup_pending"] is True
        running.output.append(b"still responsive")
        StreamPublisher(core, bindings).pump()
        assert core.get(running_name).position == len(b"still responsive")
        peer.flush()
        frames = FrameDecoder().feed(client.recv(65536))
        reply = ReplyCodec.decode(frames[0].payload)
        assert isinstance(reply, FailureReply)
        assert reply.error == "reap failed"
        assert any(frame.kind is FrameKind.CLOSE for frame in frames)
    finally:
        process.reaped = True
        peer.close()
        client.close()
        core.close()


@pytest.mark.parametrize("transient", [False, True])
def test_attach_failures_distinguish_unknown_ids_from_resource_limits(
    transient: bool,
) -> None:
    core = SessionCore(FakeFactory(), limit=1)
    core.create(NewRequest(1, "one"))
    client, owned = socket.socketpair()
    client.settimeout(1)
    peer = Peer(owned)
    peer.mark_ready()
    try:
        request = NewRequest(2, "two") if transient else AttachRequest(2, "t0.9")
        Controls.input(core, ViewerBindings()).receive(
            peer, Frame(0, FrameKind.DATA, ControlCodec.encode(request))
        )
        peer.flush()
        frame = FrameDecoder().feed(client.recv(65536))[0]
        reply = ReplyCodec.decode(frame.payload)
        assert isinstance(reply, FailureReply)
        assert reply.retryable is transient
    finally:
        peer.close()
        client.close()
        core.close()
