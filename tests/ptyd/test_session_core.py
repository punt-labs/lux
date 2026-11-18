"""Headless session authority and snapshot/tail partitions from the Z model."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Never

import pytest

if TYPE_CHECKING:
    from pytest import MonkeyPatch

pytest.importorskip("pyghostty")

from punt_lux.protocol.pty.attach import AttachRequest
from punt_lux.ptyd.core import SessionCore, SessionError
from punt_lux.ptyd.output import SessionSnapshot
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

    def pump(self) -> bytes:
        return self.output.pop(0) if self.output else b""

    def write(self, data: bytes) -> None:
        if self.refuse_write:
            raise BufferError("input full")
        self.written.append(data)

    def resize(self, cols: int, rows: int) -> None:
        self.sizes.append((cols, rows))

    def close(self) -> None:
        self.close_calls += 1
        if self.refuse_close:
            raise OSError("close failed")
        self.alive = False


class FakeFactory:
    def __init__(self) -> None:
        self.created: list[FakeProcess] = []

    def __call__(self, _request: AttachRequest) -> ProcessPort:
        process = FakeProcess()
        self.created.append(process)
        return process


def test_sessions_keep_up_with_output_without_viewers() -> None:
    factory = FakeFactory()
    core = SessionCore(factory)
    try:
        session = core.acquire(AttachRequest(1, "shell"))
        factory.created[0].output.append(b"headless output")
        assert core.pump()[0].data == b"headless output"
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
        assert core.pump()[0].start == 0
        snapshot = session.capture()
        process.output.append(b"def")
        tail = core.pump()[0]
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


def test_process_exit_is_recorded_once_and_never_respawned() -> None:
    factory = FakeFactory()
    core = SessionCore(factory)
    try:
        session = core.acquire(AttachRequest(1, "shell"))
        process = factory.created[0]
        process.alive = False
        process.exit_code = 7
        assert b"[process exited]" in core.pump()[0].data
        assert core.pump() == []
        assert core.acquire(AttachRequest(2, "shell")) is session
        assert len(factory.created) == 1
        assert session.ended
        session.write(b"ignored")
        assert process.written == []
        assert core.describe()[0]["exit_code"] == 7
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
        with pytest.raises(BufferError):
            core.pump()
        assert core.describe()[0]["state"] == "failed"
        with pytest.raises(RuntimeError, match="failed"):
            session.capture()
    finally:
        core.close()


def test_limit_and_conflicting_command_do_not_start_another_process() -> None:
    factory = FakeFactory()
    core = SessionCore(factory, limit=1)
    try:
        core.acquire(AttachRequest(1, "one", "/bin/sh"))
        with pytest.raises(SessionError, match="another command"):
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

    monkeypatch.setattr("punt_lux.ptyd.core.TerminalSession", fail)
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
