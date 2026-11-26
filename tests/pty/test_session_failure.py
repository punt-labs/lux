"""Failed terminal operations retain cleanup ownership, not a running program."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from punt_lux.pty.core import SessionCore
from punt_lux.terminal.ffi_terminal import TerminalIO
from punt_lux.terminal.output import OutputChunk
from punt_lux.wire.stream.new_request import NewRequest
from tests.pty.fake_process import FakeFactory


@pytest.mark.parametrize("operation", ["read", "feed", "process_resize", "term_resize"])
@pytest.mark.parametrize("refuse_cleanup", [False, True])
def test_failed_operation_retires_child_while_other_sessions_keep_pumping(
    operation: str, refuse_cleanup: bool
) -> None:
    factory = FakeFactory()
    core = SessionCore(factory)
    try:
        failed = core.create(NewRequest(1, "bad"))
        good_name = core.create(NewRequest(2, "good")).name
        process, good = factory.created
        process.output.append(b"unparsed")
        process.reaped = False
        process.refuse_close = refuse_cleanup
        good.output.append(b"still responsive")
        targets = {
            "read": (process, "pump"),
            "feed": (TerminalIO, "feed"),
            "process_resize": (process, "resize"),
            "term_resize": (TerminalIO, "resize"),
        }
        owner, method = targets[operation]
        with patch.object(process, "close", wraps=process.close) as close:
            with patch.object(
                owner, method, side_effect=RuntimeError("operation failed")
            ):
                if "resize" in operation:
                    with pytest.raises(RuntimeError, match="operation failed"):
                        failed.resize(100, 30)
                else:
                    with pytest.raises(RuntimeError, match="operation failed"):
                        failed.pump()
            events = core.pump()
            assert OutputChunk(good_name, 0, b"still responsive") in events
            assert failed.describe()["state"] == "failed"
            assert failed.position == 0
            assert close.call_count >= 1
            assert process.alive is refuse_cleanup
            with pytest.raises(RuntimeError, match="failed"):
                failed.capture()
            assert core.attach(failed.name) is failed
            assert len(factory.created) == 2
            calls = close.call_count
            assert core.pump() == []
            assert close.call_count > calls
            process.reaped = True
            process.refuse_close = False
            assert core.pump() == []
            calls = close.call_count
            assert not process.alive
            assert core.pump() == []
            assert close.call_count == calls
    finally:
        for process in factory.created:
            process.reaped = True
            process.refuse_close = False
        core.close()


def test_cleanup_runtime_error_does_not_replace_the_terminal_failure() -> None:
    factory = FakeFactory()
    core = SessionCore(factory)
    try:
        session = core.create(NewRequest(1, "bad"))
        process = factory.created[0]
        with (
            patch.object(process, "resize", side_effect=OSError("resize failed")),
            patch.object(process, "close", side_effect=RuntimeError("cleanup failed")),
            pytest.raises(OSError, match="resize failed"),
        ):
            session.resize(100, 30)
        assert session.describe()["state"] == "failed"
        assert process.alive
        assert core.pump() == []
        assert not process.alive
    finally:
        core.close()
