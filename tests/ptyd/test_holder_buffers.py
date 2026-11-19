"""Input backpressure and reaping tested without starting any child."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest

from punt_lux.ptyd.child import ChildLifetime
from punt_lux.ptyd.input_buffer import InputBuffer

if TYPE_CHECKING:
    from pytest import MonkeyPatch


def test_short_write_and_eagain_preserve_exact_input_order(
    monkeypatch: MonkeyPatch,
) -> None:
    queue = InputBuffer(10)
    attempted: list[bytes] = []
    actions = [2, 0, 3]

    def write(_fd: int, data: bytes | bytearray) -> int:
        attempted.append(bytes(data))
        count = actions.pop(0)
        if count == 0:
            raise BlockingIOError
        return count

    monkeypatch.setattr("punt_lux.ptyd.input_buffer.os.write", write)
    queue.append(b"hello")
    queue.flush(1)
    assert queue.pending_bytes == 3
    queue.flush(1)
    assert queue.pending_bytes == 3
    queue.flush(1)
    assert queue.pending_bytes == 0
    assert attempted == [b"hello", b"llo", b"llo"]


def test_overflow_rejected_without_discarding_existing_input() -> None:
    queue = InputBuffer(4)
    queue.append(b"abc")
    with pytest.raises(BufferError):
        queue.append(b"de")
    assert queue.pending_bytes == 3
    queue.clear()
    assert queue.pending_bytes == 0


def test_reaped_child_is_never_signalled(monkeypatch: MonkeyPatch) -> None:
    calls: list[int] = []

    def waitpid(pid: int, options: int) -> tuple[int, int]:
        assert options == os.WNOHANG
        calls.append(pid)
        return pid, 7 << 8

    def kill(_pid: int, _signal: int) -> None:
        raise AssertionError("reaped PID must not be signalled")

    monkeypatch.setattr("punt_lux.ptyd.child.os.waitpid", waitpid)
    monkeypatch.setattr("punt_lux.ptyd.child.os.kill", kill)
    child = ChildLifetime(123)
    assert child.poll()
    assert child.exit_code == 7
    child.stop()
    assert calls == [123]


@pytest.mark.parametrize("pid", [-1, 0])
def test_non_child_pid_rejected(pid: int) -> None:
    with pytest.raises(ValueError, match="pid"):
        ChildLifetime(pid)
