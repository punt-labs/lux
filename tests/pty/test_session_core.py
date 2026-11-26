"""Headless session authority and snapshot/tail partitions from the Z model."""

from __future__ import annotations

from typing import TYPE_CHECKING, Never
from unittest.mock import patch

import pytest

if TYPE_CHECKING:
    from pytest import MonkeyPatch

pytest.importorskip("pyghostty")

from punt_lux.pty.core import SessionCore, SessionError
from punt_lux.pty.fault import SessionFault
from punt_lux.pty.process_port import ProcessPort
from punt_lux.pty.session_spec import SessionSpec
from punt_lux.terminal.output import OutputChunk
from punt_lux.terminal.snapshot import restore_binary
from punt_lux.wire.stream.new_request import NewRequest
from tests.pty.fake_process import FakeFactory, FakeProcess


def output(events: list[OutputChunk | SessionFault]) -> OutputChunk:
    event = events[0]
    assert isinstance(event, OutputChunk)
    return event


def test_sessions_keep_up_with_output_without_viewers() -> None:
    factory = FakeFactory()
    core = SessionCore(factory)
    try:
        session = core.create(NewRequest(1, "shell"))
        factory.created[0].output.append(b"headless output")
        assert output(core.pump()).data == b"headless output"
        restored = restore_binary(session.capture().data)
        assert restored.text() == "headless output"
        assert core.attach(session.name) is session
        assert len(factory.created) == 1
        assert factory.created[0].close_calls == 0
    finally:
        core.close()


def test_snapshot_cut_does_not_lose_output_arriving_during_transfer() -> None:
    factory = FakeFactory()
    core = SessionCore(factory)
    try:
        session = core.create(NewRequest(1, "shell"))
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


def test_reattach_to_a_running_session_reuses_it() -> None:
    """A reconnect to a live shell must not spawn a second process."""
    factory = FakeFactory()
    core = SessionCore(factory)
    try:
        session = core.create(NewRequest(1, "shell"))
        assert core.attach(session.name) is session
        assert core.attach(session.name) is session
        assert len(factory.created) == 1
    finally:
        core.close()


def test_process_exit_is_recorded_once_and_never_respawned() -> None:
    factory = FakeFactory()
    core = SessionCore(factory)
    try:
        session = core.create(NewRequest(1, "shell"))
        process = factory.created[0]
        process.alive = False
        process.exit_code = 7
        assert b"[process exited]" in output(core.pump()).data
        assert core.pump() == []
        assert session.ended
        assert core.describe()[0]["exit_code"] == 7
        with pytest.raises(ValueError, match="unknown session"):
            core.attach(session.name)
        assert len(factory.created) == 1
    finally:
        core.close()


def test_input_and_resize_reach_only_the_selected_process() -> None:
    factory = FakeFactory()
    core = SessionCore(factory)
    try:
        first = core.create(NewRequest(1, "first"))
        core.create(NewRequest(2, "second"))
        first.write(b"one\n")
        first.resize(100, 30)
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
        session = core.create(NewRequest(1, "shell"))
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
        session = core.create(NewRequest(1, "shell"))
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
        core.create(NewRequest(1, "good"))
        core.create(NewRequest(2, "bad"))
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


def test_limit_refuses_another_process_and_keeps_the_first() -> None:
    factory = FakeFactory()
    core = SessionCore(factory, limit=1)
    try:
        core.create(NewRequest(1, "one"))
        with pytest.raises(SessionError, match="limit"):
            core.create(NewRequest(2, "two"))
        assert len(factory.created) == 1
    finally:
        core.close()


def test_a_launcher_the_daemon_does_not_list_starts_nothing() -> None:
    core = SessionCore()
    try:
        with pytest.raises(ValueError, match="unknown launcher"):
            core.create(NewRequest(1, launcher="rm-rf"))
        assert core.describe() == []
    finally:
        core.close()


def test_failed_kill_retains_ownership_for_retry() -> None:
    factory = FakeFactory()
    core = SessionCore(factory)
    name = core.create(NewRequest(1, "one")).name
    process = factory.created[0]
    process.refuse_close = True
    with pytest.raises(OSError):
        core.kill(name)
    assert core.get(name).name == name
    with pytest.raises(ValueError, match="already in use"):
        core.create(NewRequest(2, "one"))
    process.refuse_close = False
    core.close()
    assert core.describe() == []
    with pytest.raises(SessionError, match="unknown"):
        core.get(name)


def test_failed_start_and_cleanup_preserve_the_unclaimed_process(
    monkeypatch: MonkeyPatch,
) -> None:
    process = FakeProcess(refuse_close=True)

    def start(_request: NewRequest) -> ProcessPort:
        return process

    def fail(_spec: SessionSpec, _process: ProcessPort) -> Never:
        raise MemoryError("terminal construction failed")

    monkeypatch.setattr("punt_lux.pty.session_birth.TerminalSession", fail)
    core = SessionCore(start, limit=1)
    with pytest.raises(ExceptionGroup) as failure:
        core.create(NewRequest(1, "one"))
    assert len(failure.value.exceptions) == 2
    (pending,) = core.describe()
    assert pending["cleanup_pending"] is True
    assert pending["pid"] == 123
    with pytest.raises(SessionError, match="limit"):
        core.create(NewRequest(2, "other"))
    process.refuse_close = False
    core.close()
    assert core.describe() == []


def test_shutdown_attempts_every_session_despite_a_failed_close() -> None:
    factory = FakeFactory()
    core = SessionCore(factory)
    one = core.create(NewRequest(1, "one")).name
    core.create(NewRequest(2, "two"))
    factory.created[0].refuse_close = True
    with pytest.raises(ExceptionGroup):
        core.close()
    assert factory.created[1].close_calls == 1
    assert [entry["session"] for entry in core.describe()] == [one]
    factory.created[0].refuse_close = False
    core.close()


def test_killing_one_session_does_not_block_another_sessions_pump() -> None:
    factory = FakeFactory()
    core = SessionCore(factory)
    try:
        dying_name = core.create(NewRequest(1, "dying")).name
        running_name = core.create(NewRequest(2, "running")).name
        dying, running = factory.created
        dying.reaped = False
        running.output.append(b"still responsive")
        with patch("time.sleep", side_effect=AssertionError("blocking kill")):
            core.kill(dying_name)
            assert output(core.pump()).data == b"still responsive"
        assert core.describe()[-1]["cleanup_pending"] is True
        assert dying.close_calls == 1
        dying.reaped = True
        assert core.pump() == []
        assert [item["session"] for item in core.describe()] == [running_name]
    finally:
        factory.created[0].reaped = True
        core.close()
