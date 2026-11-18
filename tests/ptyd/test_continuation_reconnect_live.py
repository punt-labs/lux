"""A temporarily unencodable parser state must not freeze a reconnect forever."""

from __future__ import annotations

import shlex
import sys
import time
from pathlib import Path

import pytest

pytest.importorskip("pyghostty")
pytest.importorskip("imgui_bundle")

from punt_lux.display.terminal.remote_phase import RemotePhase
from punt_lux.display.terminal.remote_pool import RemotePool
from punt_lux.protocol.pty.attach import AttachRequest
from punt_lux.protocol.pty.control import WIRE_VERSION
from punt_lux.protocol.pty.frames import Frame, FrameKind
from punt_lux.protocol.pty.hello import HelloRequest
from punt_lux.protocol.pty.replies import SuccessReply
from punt_lux.protocol.pty.session_requests import ListRequest
from punt_lux.ptyd.snapshot import snapshot_version
from tests.ptyd.wire_client import WireClient

pytestmark = pytest.mark.integration


def test_reconnect_recovers_after_parser_continuation_returns_to_ground(
    daemon: Path,
) -> None:
    code = (
        "import sys,time; sys.stdin.readline(); "
        "sys.stdout.buffer.write(bytes([27])+b']2;'+b'x'*70000); sys.stdout.flush(); "
        "time.sleep(1.5); "
        "sys.stdout.buffer.write(bytes([27])+b'\\\\'+b'GROUND_READY\\n'); "
        "sys.stdout.flush(); sys.stdin.readline()"
    )
    command = shlex.join([sys.executable, "-u", "-c", code])
    owner = WireClient(daemon)
    try:
        owner.request(HelloRequest(1, WIRE_VERSION, snapshot_version()))
        reply = owner.request(AttachRequest(2, "continuation", command))
        assert isinstance(reply, SuccessReply)
        channel, _initial = owner.snapshot(dict(reply.result))
        owner.send(Frame(channel, FrameKind.DATA, b"go\n"))
        request_id = 3
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            status = owner.request(ListRequest(request_id))
            request_id += 1
            assert isinstance(status, SuccessReply)
            sessions = status.result["sessions"]
            assert isinstance(sessions, list)
            if sessions[0]["position"] >= 70004:
                original_pid = sessions[0]["pid"]
                break
            time.sleep(0.005)
        else:
            pytest.fail("program did not enter the long parser sequence")
    finally:
        owner.close()
    pool = RemotePool(daemon)
    try:
        session = pool.get("continuation", command)
        observed_wait = False
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline:
            pool.pump()
            observed_wait |= session.phase is RemotePhase.DISCONNECTED
            if session.phase is RemotePhase.READY:
                assert observed_wait, (
                    "test did not exercise unavailable initial snapshot"
                )
                assert "GROUND_READY" in session.view.term.text()
                status_client = WireClient(daemon)
                try:
                    status_client.request(
                        HelloRequest(1, WIRE_VERSION, snapshot_version())
                    )
                    reply = status_client.request(ListRequest(2))
                    assert isinstance(reply, SuccessReply)
                    sessions = reply.result["sessions"]
                    assert isinstance(sessions, list)
                    assert sessions[0]["pid"] == original_pid
                finally:
                    status_client.close()
                return
            time.sleep(0.005)
        pytest.fail(f"reconnect stayed {session.status} after parser recovery")
    finally:
        pool.close()
