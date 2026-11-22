"""A bounded finite output burst: fast viewer progresses, slow viewer repaints."""

from __future__ import annotations

import json
import shlex
import struct
import sys
import time
from pathlib import Path
from typing import cast

import pytest

pytest.importorskip("pyghostty")

from punt_lux.protocol.pty.attach import AttachRequest
from punt_lux.protocol.pty.control import WIRE_VERSION
from punt_lux.protocol.pty.frames import Frame, FrameKind
from punt_lux.protocol.pty.hello import HelloRequest
from punt_lux.protocol.pty.replies import SuccessReply
from punt_lux.terminal.snapshot import restore_binary, snapshot_version
from tests.ptyd.wire_client import WireClient

pytestmark = pytest.mark.integration


def test_stalled_viewer_catches_up_without_blocking_fast_viewer(daemon: Path) -> None:
    code = (
        "import sys; print('READY',flush=True); sys.stdin.readline(); "
        "sys.stdout.write('x'*(5*1024*1024)+'\\nEND\\n'); sys.stdout.flush(); "
        "sys.stdin.readline()"
    )
    command = shlex.join([sys.executable, "-u", "-c", code])
    slow, fast = WireClient(daemon, auto_credit=False), WireClient(daemon)
    try:
        for client in (slow, fast):
            assert isinstance(
                client.request(HelloRequest(1, WIRE_VERSION, snapshot_version())),
                SuccessReply,
            )
        reply = slow.request(AttachRequest(2, "burst", command))
        assert isinstance(reply, SuccessReply)
        slow_channel, initial = slow.snapshot(dict(reply.result))
        slow.send(
            Frame(slow_channel, FrameKind.CREDIT, struct.pack("<I", len(initial.data)))
        )
        reply = fast.request(AttachRequest(2, "burst", command))
        assert isinstance(reply, SuccessReply)
        channel, first = fast.snapshot(dict(reply.result))
        viewer = restore_binary(first.data)
        fast.send(Frame(channel, FrameKind.DATA, b"go\n"))
        deadline = time.monotonic() + 8
        while "END" not in viewer.text() and time.monotonic() < deadline:
            frame = fast.next(channel)
            if frame.kind is FrameKind.DATA:
                viewer.feed(frame.payload)
            elif frame.kind is FrameKind.SNAPSHOT_START:
                raw = cast("dict[str, object]", json.loads(frame.payload))
                _, checkpoint = fast.snapshot(raw)
                viewer = restore_binary(checkpoint.data)
        assert "END" in viewer.text()
        # Return old in-flight debt. This must not mint an extra window when
        # the pending tail is replaced by the current authoritative snapshot.
        received = 0
        while received < 256 * 1024:
            frame = slow.next(slow_channel)
            assert frame.kind is FrameKind.DATA
            received += len(frame.payload)
        slow.send(Frame(slow_channel, FrameKind.CREDIT, struct.pack("<I", received)))
        frame = slow.next(slow_channel)
        assert frame.kind is FrameKind.SNAPSHOT_START
        metadata = cast("dict[str, object]", json.loads(frame.payload))
        # Enable normal consumption now so a snapshot larger than one window
        # can complete, returning credit fragment by fragment.
        slow.enable_credit()
        _, checkpoint = slow.snapshot(metadata)
        caught_up = restore_binary(checkpoint.data)
        assert "END" in caught_up.text()
    finally:
        slow.close()
        fast.close()
