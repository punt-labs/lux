"""Every shutdown signal reaches the group; a routine refusal after exit is quiet."""

from __future__ import annotations

import os
import signal
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from punt_lux.ptyd.leader_status import LeaderStatus
from punt_lux.ptyd.process_group import ProcessGroup

_EXITED = SimpleNamespace(si_status=0, si_code=os.CLD_EXITED)


def test_a_group_missing_at_sighup_still_gets_sigkill() -> None:
    """ESRCH can precede group creation, so it must not cancel the later SIGKILL."""
    with patch(
        "punt_lux.ptyd.process_group.os.killpg",
        side_effect=[ProcessLookupError, None],
    ) as killpg:
        group = ProcessGroup(123, LeaderStatus(123))
        group.signal(signal.SIGHUP)
        group.signal(signal.SIGKILL)
    assert [c.args[1] for c in killpg.call_args_list] == [
        signal.SIGHUP,
        signal.SIGKILL,
    ]


def test_a_refused_sighup_after_exit_still_sends_sigkill() -> None:
    """EPERM does not prove the group is empty: a member may become signallable."""
    with (
        patch("punt_lux.ptyd.leader_status.os.waitid", return_value=_EXITED),
        patch(
            "punt_lux.ptyd.process_group.os.killpg",
            side_effect=[PermissionError, None],
        ) as killpg,
    ):
        group = ProcessGroup(123, LeaderStatus(123))
        group.signal(signal.SIGHUP)
        group.signal(signal.SIGKILL)
    assert [c.args[1] for c in killpg.call_args_list] == [
        signal.SIGHUP,
        signal.SIGKILL,
    ]


def test_a_refusal_after_exit_logs_at_debug_only(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with (
        patch("punt_lux.ptyd.leader_status.os.waitid", return_value=_EXITED),
        patch("punt_lux.ptyd.process_group.os.killpg", side_effect=PermissionError),
        caplog.at_level("DEBUG", logger="punt_lux.ptyd"),
    ):
        group = ProcessGroup(123, LeaderStatus(123))
        group.signal(signal.SIGHUP)
        group.signal(signal.SIGKILL)
    assert [r.levelname for r in caplog.records] == ["DEBUG", "DEBUG"]
    assert "EPERM" in caplog.text


def test_eperm_while_the_leader_runs_is_raised_every_time() -> None:
    with (
        patch("punt_lux.ptyd.leader_status.os.waitid", return_value=None),
        patch(
            "punt_lux.ptyd.process_group.os.killpg", side_effect=PermissionError
        ) as killpg,
    ):
        group = ProcessGroup(123, LeaderStatus(123))
        for sig in (signal.SIGHUP, signal.SIGKILL):
            with pytest.raises(PermissionError):
                group.signal(sig)
    assert killpg.call_count == 2


def test_a_real_exited_shell_group_signals_without_error_or_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """No mocks: a real zombie leader with no other member, as after `exit`.

    macOS refuses the group signal with EPERM; Linux accepts it. Either way
    both shutdown signals complete without raising and nothing is warned.
    """
    pid = os.fork()
    if pid == 0:
        os.setsid()
        os._exit(0)
    try:
        os.waitid(os.P_PID, pid, os.WEXITED | os.WNOWAIT)
        group = ProcessGroup(pid, LeaderStatus(pid))
        with caplog.at_level("WARNING", logger="punt_lux.ptyd"):
            group.signal(signal.SIGHUP)
            group.signal(signal.SIGKILL)
        assert caplog.records == []
    finally:
        os.waitpid(pid, 0)
