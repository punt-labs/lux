"""Independent daemon integration: clients leave; the held program does not."""

from __future__ import annotations

import shlex
import sys
import time
from pathlib import Path

import pytest

pytest.importorskip("pyghostty")

from punt_lux.protocol.pty.attach import AttachRequest
from punt_lux.protocol.pty.control import WIRE_VERSION
from punt_lux.protocol.pty.frames import Frame, FrameKind
from punt_lux.protocol.pty.hello import HelloRequest
from punt_lux.protocol.pty.replies import FailureReply, SuccessReply
from punt_lux.protocol.pty.session_requests import KillRequest, ListRequest
from punt_lux.ptyd.snapshot import restore_binary, snapshot_version
from tests.ptyd.wire_client import WireClient

pytestmark = pytest.mark.integration


def hello(client: WireClient, request_id: int = 1) -> SuccessReply:
    reply = client.request(HelloRequest(request_id, WIRE_VERSION, snapshot_version()))
    assert isinstance(reply, SuccessReply)
    return reply


def test_program_survives_client_disconnect_and_reconnect(daemon: Path) -> None:
    code = (
        "import sys; print('READY',flush=True); "
        "line=sys.stdin.readline(); print('ECHO:'+line.strip(),flush=True); "
        "sys.stdin.readline()"
    )
    command = shlex.join([sys.executable, "-u", "-c", code])
    first = WireClient(daemon)
    try:
        hello(first)
        reply = first.request(AttachRequest(2, "persistent", command))
        assert isinstance(reply, SuccessReply)
        channel, checkpoint = first.snapshot(dict(reply.result))
        viewer = restore_binary(checkpoint.data)
        deadline = time.monotonic() + 4
        while "READY" not in viewer.text() and time.monotonic() < deadline:
            frame = first.next(channel)
            assert frame.kind is FrameKind.DATA
            viewer.feed(frame.payload)
        assert "READY" in viewer.text()
        listing = first.request(ListRequest(3))
        assert isinstance(listing, SuccessReply)
        sessions = listing.result["sessions"]
        assert isinstance(sessions, list)
        original_pid = sessions[0]["pid"]
        first.send(Frame(channel, FrameKind.DATA, b"hello\n"))
    finally:
        first.close()
    time.sleep(0.1)
    second = WireClient(daemon)
    try:
        hello(second)
        listing = second.request(ListRequest(2))
        assert isinstance(listing, SuccessReply)
        sessions = listing.result["sessions"]
        assert isinstance(sessions, list)
        assert sessions[0]["pid"] == original_pid
        reply = second.request(AttachRequest(3, "persistent", command))
        assert isinstance(reply, SuccessReply)
        channel, checkpoint = second.snapshot(dict(reply.result))
        viewer = restore_binary(checkpoint.data)
        deadline = time.monotonic() + 4
        while "ECHO:hello" not in viewer.text() and time.monotonic() < deadline:
            frame = second.next(channel)
            assert frame.kind is FrameKind.DATA
            viewer.feed(frame.payload)
        assert "ECHO:hello" in viewer.text()
        assert isinstance(second.request(KillRequest(4, "persistent")), SuccessReply)
    finally:
        second.close()


def test_request_before_hello_cannot_start_a_program(daemon: Path) -> None:
    client = WireClient(daemon)
    try:
        reply = client.request(AttachRequest(1, "forbidden", "/bin/sh"))
        assert isinstance(reply, FailureReply)
        hello(client, 2)
        listing = client.request(ListRequest(3))
        assert isinstance(listing, SuccessReply)
        assert listing.result["sessions"] == []
    finally:
        client.close()


def test_version_mismatch_does_not_mark_peer_ready(daemon: Path) -> None:
    client = WireClient(daemon)
    try:
        reply = client.request(HelloRequest(1, WIRE_VERSION + 1, snapshot_version()))
        assert isinstance(reply, FailureReply)
        reply = client.request(AttachRequest(2, "forbidden"))
        assert isinstance(reply, FailureReply)
    finally:
        client.close()
