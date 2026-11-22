"""Dispatch answers every decoded operation, never mistaking one for kill."""

from __future__ import annotations

import pytest

from punt_lux.protocol.pty.control import ControlCodec, Request
from punt_lux.protocol.pty.new_request import NewRequest
from punt_lux.protocol.pty.replies import FailureReply, ReplyCodec
from punt_lux.protocol.pty.session_events import WatchRequest
from punt_lux.ptyd.control_dispatch import ControlDispatch
from punt_lux.ptyd.viewers import ViewerBindings
from tests.ptyd.stream_fakes import QueuedCore, RecordingPeer


@pytest.mark.parametrize("request_", [NewRequest(7, "work"), WatchRequest(7)])
def test_unimplemented_operation_is_refused_not_run_as_kill(request_: Request) -> None:
    decoded = ControlCodec.decode(ControlCodec.encode(request_))
    peer = RecordingPeer()
    dispatch = ControlDispatch(QueuedCore(), ViewerBindings())  # type: ignore[arg-type]  # fake core

    dispatch.execute(peer, decoded)  # type: ignore[arg-type]  # fake peer

    reply = ReplyCodec.decode(peer.frames[0].payload)
    assert isinstance(reply, FailureReply)
    assert reply.request_id == 7
    assert reply.error == f"unsupported operation {request_.OP}"
    assert not reply.retryable
    assert not peer.closed
