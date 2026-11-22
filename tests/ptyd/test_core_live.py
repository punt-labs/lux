"""A real session core works headless and gives independent viewer snapshots."""

from __future__ import annotations

import os
import shlex
import sys
import time

import pytest

pytest.importorskip("pyghostty")

from punt_lux.protocol.pty.attach import AttachRequest
from punt_lux.ptyd.core import SessionCore
from punt_lux.terminal.output import OutputChunk
from punt_lux.terminal.snapshot import restore_binary

pytestmark = pytest.mark.integration


class CoreOutputWait:
    @staticmethod
    def until(core: SessionCore, text: bytes) -> bytes:
        deadline = time.monotonic() + 8
        output = bytearray()
        while time.monotonic() < deadline:
            for chunk in core.pump():
                assert isinstance(chunk, OutputChunk)
                output.extend(chunk.data)
            if text in output:
                return bytes(output)
            time.sleep(0.005)
        pytest.fail(f"expected {text!r}, got {bytes(output)!r}")


def test_headless_program_can_be_inspected_then_used_without_respawn() -> None:
    code = (
        "import sys; print('READY',flush=True); line=sys.stdin.readline(); "
        "print('ECHO:'+line.strip(),flush=True)"
    )
    command = shlex.join([sys.executable, "-u", "-c", code])
    core = SessionCore()
    pid = 0
    try:
        session = core.acquire(AttachRequest(1, "headless", command))
        description = session.describe()
        assert isinstance(description["pid"], int)
        pid = description["pid"]
        CoreOutputWait.until(core, b"READY")
        first = session.capture()
        assert "READY" in restore_binary(first.data).text()
        session.write(b"hello\n")
        CoreOutputWait.until(core, b"ECHO:hello")
        assert core.acquire(AttachRequest(2, "headless", command)) is session
        second = session.capture()
        assert second.position > first.position
        assert "ECHO:hello" in restore_binary(second.data).text()
        assert len(core.describe()) == 1
    finally:
        core.close()
    with pytest.raises(ChildProcessError):
        os.waitpid(pid, os.WNOHANG)
