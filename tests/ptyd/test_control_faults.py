"""Transport-level construction/cleanup faults do not terminate other sessions."""

from __future__ import annotations

import socket
from typing import TYPE_CHECKING, Never

import pytest

pytest.importorskip("pyghostty")

from punt_lux.protocol.pty.attach import AttachRequest
from punt_lux.protocol.pty.control import ControlCodec
from punt_lux.protocol.pty.frames import Frame, FrameDecoder, FrameKind
from punt_lux.protocol.pty.replies import FailureReply, ReplyCodec
from punt_lux.ptyd.control_input import ControlInput
from punt_lux.ptyd.core import SessionCore
from punt_lux.ptyd.peer import Peer
from punt_lux.ptyd.process_port import ProcessPort
from punt_lux.ptyd.viewers import ViewerBindings
from tests.ptyd.test_session_core import FakeFactory

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
    core.acquire(AttachRequest(1, "good"))
    good = factory.created[0]
    client, owned = socket.socketpair()
    client.settimeout(1)
    peer = Peer(owned)
    peer.mark_ready()
    control = ControlInput(core, ViewerBindings())

    def fail(_request: AttachRequest, _process: ProcessPort) -> Never:
        factory.created[-1].refuse_close = refuse_cleanup
        raise fault_type(message)

    monkeypatch.setattr("punt_lux.ptyd.core.TerminalSession", fail)
    try:
        request = AttachRequest(7, "bad")
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
        assert peer.ready
        assert good.alive and good.close_calls == 0
        assert core.get("good").name == "good"
        if refuse_cleanup:
            assert core.describe()[-1] == {
                "session": "bad",
                "pid": 123,
                "cleanup_pending": True,
            }
        else:
            assert len(core.describe()) == 1
    finally:
        for process in factory.created:
            process.refuse_close = False
        peer.close()
        client.close()
        core.close()
