"""Headless session authority and snapshot/tail partitions from the Z model."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Never
from unittest.mock import patch

import pytest

if TYPE_CHECKING:
    from pytest import MonkeyPatch

pytest.importorskip("pyghostty")

from punt_lux.protocol.pty.attach import AttachRequest
from punt_lux.ptyd.core import SessionCore, SessionError
from punt_lux.ptyd.fault import SessionFault
from punt_lux.ptyd.output import OutputChunk, SessionSnapshot
from punt_lux.ptyd.process_port import ProcessPort
from punt_lux.ptyd.snapshot import restore_binary


@dataclass
class FakeProcess:
    """Deterministic IO port; no real shell, socket or window is started."""

    alive: bool = True
    pid: int = 123
    exit_code: int | None = None
    output: list[bytes] = field(default_factory=list)
    written: list[bytes] = field(default_factory=list)
    sizes: list[tuple[int, int]] = field(default_factory=list)
    close_calls: int = 0
    refuse_close: bool = False
    refuse_write: bool = False
    reaped: bool = True

    def pump(self) -> bytes:
        return self.output.pop(0) if self.output else b""

    def write(self, data: bytes) -> None:
        if self.refuse_write:
            raise BufferError("input full")
        self.written.append(data)

    def resize(self, cols: int, rows: int) -> None:
        self.sizes.append((cols, rows))

    def close(self) -> bool:
        if self.alive:
            self.close_calls += 1
        if self.refuse_close:
            raise OSError("close failed")
        self.alive = False
        return self.reaped


class FakeFactory:
    def __init__(self) -> None:
        self.created: list[FakeProcess] = []

    def __call__(self, _request: AttachRequest) -> ProcessPort:
        process = FakeProcess()
        self.created.append(process)
        return process


def output(events: list[OutputChunk | SessionFault]) -> OutputChunk:
    event = events[0]
    assert isinstance(event, OutputChunk)
    return event


def test_sessions_keep_up_with_output_without_viewers() -> None:
    factory = FakeFactory()
    core = SessionCore(factory)
    try:
        session = core.acquire(AttachRequest(1, "shell"))
        factory.created[0].output.append(b"headless output")
        assert output(core.pump()).data == b"headless output"
        restored = restore_binary(session.capture().data)
        assert restored.text() == "headless output"
        assert core.acquire(AttachRequest(2, "shell")) is session
        assert len(factory.created) == 1
        assert factory.created[0].close_calls == 0
    finally:
        core.close()


def test_snapshot_cut_does_not_lose_output_arriving_during_transfer() -> None:
    factory = FakeFactory()
    core = SessionCore(factory)
    try:
        session = core.acquire(AttachRequest(1, "shell"))
        process = factory.created[0]
        process.output.append(b"abc")
        assert output(core.pump()).start == 0
        snapshot = session.capture()
        process.output.append(b"def")
        tail = output(core.pump())
        assert snapshot.position == tail.start == 3
        viewer = restore_binary(snapshot.data)
        assert viewer.text() == "abc"
        viewer.feed(tail.data)
        assert viewer.text() == "abcdef"
        assert tail.end == session.position == 6
    finally:
        core.close()


def test_snapshot_metadata_and_binary_transfer_rejoin() -> None:
    factory = FakeFactory()
    core = SessionCore(factory)
    try:
        snapshot = core.acquire(AttachRequest(1, "shell")).capture()
        assert SessionSnapshot.from_dict(snapshot.to_dict(), snapshot.data) == snapshot
        assert "data" not in snapshot.to_dict()
        with pytest.raises(ValueError, match="length"):
            SessionSnapshot.from_dict(snapshot.to_dict(), snapshot.data[:-1])
    finally:
        core.close()


def test_reattach_to_a_running_session_reuses_it() -> None:
    """A reconnect to a live shell must not spawn a second process."""
    factory = FakeFactory()
    core = SessionCore(factory)
    try:
        session = core.acquire(AttachRequest(1, "shell"))
        assert core.acquire(AttachRequest(2, "shell")) is session
        assert len(factory.created) == 1
    finally:
        core.close()


def test_exit_is_recorded_once_then_reattach_spawns_a_fresh_shell() -> None:
    """Typing `exit` ends the shell; the next attach must start a new one.

    The daemon retains the exited session only until the exit is reported.
    A fresh attach to the same name then gets a live shell, so the terminal
    is never stuck showing a dead process with no way back to a prompt.
    """
    factory = FakeFactory()
    core = SessionCore(factory)
    try:
        session = core.acquire(AttachRequest(1, "shell"))
        process = factory.created[0]
        process.alive = False
        process.exit_code = 7
        assert b"[process exited]" in output(core.pump()).data
        assert core.pump() == []
        assert session.ended
        assert core.describe()[0]["exit_code"] == 7

        fresh = core.acquire(AttachRequest(2, "shell"))
        assert fresh is not session
        assert not fresh.ended
        assert len(factory.created) == 2
    finally:
        core.close()


def test_reattach_after_exit_is_stable_while_the_dead_shell_is_still_reaping() -> None:
    """A slow-reaping predecessor must not block the fresh shell or later frames.

    The display re-attaches every rendered frame. If the exited process has not
    finished reaping, the fresh session must still spawn, and the next frame's
    attach must reuse that fresh session rather than raise on the retiring one.
    """
    factory = FakeFactory()
    core = SessionCore(factory)
    try:
        session = core.acquire(AttachRequest(1, "shell"))
        process = factory.created[0]
        process.alive = False
        process.exit_code = 0
        process.reaped = False  # close() returns False: lingers in retirement
        assert b"[process exited]" in output(core.pump()).data
        core.pump()

        fresh = core.acquire(AttachRequest(2, "shell"))
        assert fresh is not session
        assert core.acquire(AttachRequest(3, "shell")) is fresh
        assert len(factory.created) == 2
    finally:
        core.close()


def test_input_and_resize_reach_only_the_selected_process() -> None:
    factory = FakeFactory()
    core = SessionCore(factory)
    try:
        first = core.acquire(AttachRequest(1, "first"))
        core.acquire(AttachRequest(2, "second"))
        first.write(b"one\n")
        core.resize("first", 100, 30)
        assert factory.created[0].written == [b"one\n"]
        assert factory.created[1].written == []
        assert factory.created[0].sizes == [(100, 30)]
        assert (first.capture().cols, first.capture().rows) == (100, 30)
    finally:
        core.close()


def test_authoritative_parser_answers_queries_once() -> None:
    factory = FakeFactory()
    core = SessionCore(factory)
    try:
        session = core.acquire(AttachRequest(1, "shell"))
        process = factory.created[0]
        process.output.append(bytes([27]) + b"[5n")
        core.pump()
        assert process.written == [bytes([27]) + b"[0n"]
        restore_binary(session.capture().data)  # decoding generates no second reply
        assert len(process.written) == 1
    finally:
        core.close()


def test_parser_callback_failure_cannot_publish_a_mislabelled_snapshot() -> None:
    factory = FakeFactory()
    core = SessionCore(factory)
    try:
        session = core.acquire(AttachRequest(1, "shell"))
        process = factory.created[0]
        process.refuse_write = True
        process.output.append(bytes([27]) + b"[5n")
        events = core.pump()
        assert isinstance(events[0], SessionFault)
        assert core.describe()[0]["state"] == "failed"
        assert not process.alive
        assert process.close_calls == 1
        with pytest.raises(RuntimeError, match="failed"):
            session.capture()
    finally:
        core.close()


def test_one_session_fault_does_not_discard_another_sessions_output() -> None:
    factory = FakeFactory()
    core = SessionCore(factory)
    try:
        core.acquire(AttachRequest(1, "good"))
        core.acquire(AttachRequest(2, "bad"))
        factory.created[0].output.append(b"retained")
        factory.created[1].refuse_write = True
        factory.created[1].output.append(bytes([27]) + b"[5n")
        events = core.pump()
        assert isinstance(events[0], OutputChunk)
        assert events[0].data == b"retained"
        assert isinstance(events[1], SessionFault)
        assert core.pump() == []
    finally:
        core.close()


def test_limit_and_conflicting_command_do_not_start_another_process() -> None:
    factory = FakeFactory()
    core = SessionCore(factory, limit=1)
    try:
        core.acquire(AttachRequest(1, "one", "/bin/sh"))
        with pytest.raises(ValueError, match="another command"):
            core.acquire(AttachRequest(2, "one", "/bin/zsh"))
        with pytest.raises(SessionError, match="limit"):
            core.acquire(AttachRequest(3, "two"))
        assert len(factory.created) == 1
    finally:
        core.close()


def test_failed_kill_retains_ownership_for_retry() -> None:
    factory = FakeFactory()
    core = SessionCore(factory)
    core.acquire(AttachRequest(1, "one"))
    process = factory.created[0]
    process.refuse_close = True
    with pytest.raises(OSError):
        core.kill("one")
    assert core.get("one").name == "one"
    process.refuse_close = False
    core.close()
    assert core.describe() == []
    with pytest.raises(SessionError, match="unknown"):
        core.get("one")


def test_failed_start_and_cleanup_preserve_the_unclaimed_process(
    monkeypatch: MonkeyPatch,
) -> None:
    process = FakeProcess(refuse_close=True)

    def start(_request: AttachRequest) -> ProcessPort:
        return process

    def fail(_request: AttachRequest, _process: ProcessPort) -> Never:
        raise MemoryError("terminal construction failed")

    monkeypatch.setattr("punt_lux.ptyd.session_birth.TerminalSession", fail)
    core = SessionCore(start)
    with pytest.raises(ExceptionGroup) as failure:
        core.acquire(AttachRequest(1, "one"))
    assert len(failure.value.exceptions) == 2
    assert core.describe() == [{"session": "one", "pid": 123, "cleanup_pending": True}]
    with pytest.raises(SessionError, match="cleanup"):
        core.acquire(AttachRequest(2, "one"))
    process.refuse_close = False
    core.close()
    assert core.describe() == []


def test_shutdown_attempts_every_session_despite_a_failed_close() -> None:
    factory = FakeFactory()
    core = SessionCore(factory)
    core.acquire(AttachRequest(1, "one"))
    core.acquire(AttachRequest(2, "two"))
    factory.created[0].refuse_close = True
    with pytest.raises(ExceptionGroup):
        core.close()
    assert factory.created[1].close_calls == 1
    assert [entry["session"] for entry in core.describe()] == ["one"]
    factory.created[0].refuse_close = False
    core.close()


def test_killing_one_session_does_not_block_another_sessions_pump() -> None:
    factory = FakeFactory()
    core = SessionCore(factory)
    try:
        core.acquire(AttachRequest(1, "dying"))
        core.acquire(AttachRequest(2, "running"))
        dying, running = factory.created
        dying.reaped = False
        running.output.append(b"still responsive")
        with patch("time.sleep", side_effect=AssertionError("blocking kill")):
            core.kill("dying")
            assert output(core.pump()).data == b"still responsive"
        assert core.describe()[-1]["cleanup_pending"] is True
        assert dying.close_calls == 1
        with pytest.raises(SessionError, match="cleanup"):
            core.acquire(AttachRequest(3, "dying"))
        dying.reaped = True
        assert core.pump() == []
        assert [item["session"] for item in core.describe()] == ["running"]
    finally:
        factory.created[0].reaped = True
        core.close()
