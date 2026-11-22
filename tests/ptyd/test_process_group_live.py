"""Real PTY descendants cannot outlive group cleanup, even after leader exit."""

from __future__ import annotations

import contextlib
import os
import shlex
import sys
import time

import pytest

from punt_lux.protocol.pty.attach import AttachRequest
from punt_lux.ptyd.core import SessionCore
from punt_lux.terminal.output import OutputChunk

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("leader_exits", [False, True])
def test_group_cleanup_closes_descendant_liveness_pipe(leader_exits: bool) -> None:
    reader, writer = os.pipe()
    os.set_inheritable(writer, True)
    os.set_blocking(reader, False)
    code = f"""
import os, signal, time
signal.signal(signal.SIGHUP, signal.SIG_IGN)
print(f'LEADER={{os.getpid()}} SID={{os.getsid(0)}} GROUP={{os.getpgrp()}}', flush=True)
if os.fork() == 0:
    os.write({writer}, b'alive')
    while True:
        time.sleep(1)
print('READY', flush=True)
if {leader_exits!r}:
    raise SystemExit(0)
while True:
    time.sleep(1)
"""
    core = SessionCore()
    try:
        session = core.acquire(
            AttachRequest(1, "group", shlex.join([sys.executable, "-u", "-c", code]))
        )
        pid = session.describe()["pid"]
        os.close(writer)
        writer = -1
        output = bytearray()
        alive = b""
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            for chunk in core.pump():
                assert isinstance(chunk, OutputChunk)
                output.extend(chunk.data)
            with contextlib.suppress(BlockingIOError):
                alive += os.read(reader, 64)
            if b"READY" in output and alive == b"alive":
                break
            time.sleep(0.005)
        assert alive == b"alive", output
        assert f"LEADER={pid} SID={pid} GROUP={pid}".encode() in output
        core.kill("group")
        assert any(item.get("cleanup_pending") for item in core.describe())
        eof = False
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            core.pump()
            with contextlib.suppress(BlockingIOError):
                eof = os.read(reader, 64) == b""
            if eof and not core.describe():
                break
            time.sleep(0.005)
        assert eof, "a descendant still holds the liveness pipe open"
        assert core.describe() == []
        assert isinstance(pid, int)
        with pytest.raises(ChildProcessError):
            os.waitpid(pid, os.WNOHANG)
    finally:
        core.close()
        os.close(reader)
        if writer != -1:
            os.close(writer)
