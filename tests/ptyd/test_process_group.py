"""A process group is signalled until the kernel shows it has no member left."""

from __future__ import annotations

import os
import signal
import time
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from punt_lux.ptyd.leader_status import LeaderStatus
from punt_lux.ptyd.process_group import ProcessGroup


def test_missing_group_is_never_signalled_again() -> None:
    with patch(
        "punt_lux.ptyd.process_group.os.killpg", side_effect=ProcessLookupError
    ) as killpg:
        group = ProcessGroup(123, LeaderStatus(123))
        group.signal(signal.SIGHUP)
        group.signal(signal.SIGKILL)
    killpg.assert_called_once_with(123, signal.SIGHUP)


def test_eperm_after_the_leader_exited_empties_the_group() -> None:
    status = SimpleNamespace(si_status=0, si_code=os.CLD_EXITED)
    with (
        patch("punt_lux.ptyd.leader_status.os.waitid", return_value=status),
        patch(
            "punt_lux.ptyd.process_group.os.killpg", side_effect=PermissionError
        ) as killpg,
    ):
        group = ProcessGroup(123, LeaderStatus(123))
        group.signal(signal.SIGHUP)
        group.signal(signal.SIGKILL)
    killpg.assert_called_once_with(123, signal.SIGHUP)


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


def test_a_live_member_keeps_receiving_signals() -> None:
    with patch("punt_lux.ptyd.process_group.os.killpg") as killpg:
        group = ProcessGroup(123, LeaderStatus(123))
        group.signal(signal.SIGHUP)
        group.signal(signal.SIGKILL)
    assert [c.args[1] for c in killpg.call_args_list] == [
        signal.SIGHUP,
        signal.SIGKILL,
    ]


def test_a_real_exited_shell_group_is_signalled_once() -> None:
    """No mocks: a real zombie leader with no other member, as after `exit`."""
    pid = os.fork()
    if pid == 0:
        os.setsid()
        os._exit(0)
    leader = LeaderStatus(pid)
    deadline = time.monotonic() + 2
    while not leader.exited():
        assert time.monotonic() < deadline
        time.sleep(0.005)
    group = ProcessGroup(pid, leader)
    with patch("punt_lux.ptyd.process_group.os.killpg", wraps=os.killpg) as killpg:
        group.signal(signal.SIGHUP)
        group.signal(signal.SIGKILL)
    assert killpg.call_count == 1
    os.waitpid(pid, 0)
