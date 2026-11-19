"""Real PTY/process integration, run explicitly and under an outer timeout."""

from __future__ import annotations

import os
import sys
import time
from typing import TYPE_CHECKING, Never

import pytest

if TYPE_CHECKING:
    from pytest import MonkeyPatch

from punt_lux.ptyd.holder import PtyHolder

pytestmark = pytest.mark.integration


class OutputWait:
    """Accumulate output up to a hard per-test deadline, never blocking IO."""

    @staticmethod
    def until(holder: PtyHolder, text: bytes, seconds: float = 8) -> bytes:
        deadline = time.monotonic() + seconds
        output = bytearray()
        while time.monotonic() < deadline:
            output.extend(holder.pump())
            if text in output:
                return bytes(output)
            time.sleep(0.005)
        pytest.fail(f"did not receive {text!r}; output was {bytes(output)!r}")

    @staticmethod
    def exited(holder: PtyHolder) -> None:
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            holder.pump()
            if holder.exit_code is not None and holder.reap():
                return
            time.sleep(0.005)
        pytest.fail("child did not exit")


def test_large_input_reaches_program_without_short_write_loss() -> None:
    code = (
        "import sys,tty; tty.setraw(0); print('READY',flush=True); "
        "data=sys.stdin.buffer.read(20000); print('COUNT='+str(len(data)),flush=True)"
    )
    holder = PtyHolder([sys.executable, "-u", "-c", code])
    try:
        OutputWait.until(holder, b"READY")
        holder.write(b"x" * 20_000)
        assert b"COUNT=20000" in OutputWait.until(holder, b"COUNT=20000")
        OutputWait.exited(holder)
        assert holder.exit_code == 0
    finally:
        holder.close()
    holder.close()
    with pytest.raises(ChildProcessError):
        os.waitpid(holder.pid, os.WNOHANG)


def test_exit_status_and_final_output_are_preserved() -> None:
    holder = PtyHolder(
        [sys.executable, "-u", "-c", "print('last output'); raise SystemExit(7)"]
    )
    try:
        assert b"last output" in OutputWait.until(holder, b"last output")
        OutputWait.exited(holder)
        assert holder.exit_code == 7
    finally:
        holder.close()
    with pytest.raises(ChildProcessError):
        os.waitpid(holder.pid, os.WNOHANG)


def test_invalid_exec_argument_still_exits_child_safely() -> None:
    holder = PtyHolder(["bad" + chr(0)])
    try:
        assert b"exec failed" in OutputWait.until(holder, b"exec failed")
        OutputWait.exited(holder)
        assert holder.exit_code == 127
    finally:
        holder.close()


def test_unexpected_exec_exception_cannot_unwind_into_parent(
    monkeypatch: MonkeyPatch,
) -> None:
    def fail(_argv: str, _args: list[str], _env: dict[str, str]) -> Never:
        raise RuntimeError("unexpected exec hook failure")

    monkeypatch.setattr("punt_lux.ptyd.pty_spawn.os.execvpe", fail)
    holder = PtyHolder(["unused"])
    try:
        OutputWait.exited(holder)
        assert holder.exit_code == 127
    finally:
        holder.close()


def test_exec_failure_does_not_return_into_parent_python_code() -> None:
    holder = PtyHolder(["/no/such/lux-spike-program"])
    try:
        assert b"exec failed" in OutputWait.until(holder, b"exec failed")
        OutputWait.exited(holder)
        assert holder.exit_code == 127
    finally:
        holder.close()
