"""Group signalling and nonblocking reaping use a grace deadline without PID reuse."""

from __future__ import annotations

import os
import signal
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from punt_lux.ptyd.child import ChildLifetime
from punt_lux.ptyd.terminal_child import TerminalChild


def test_stop_signals_group_once_then_reaps_after_grace_without_sleeping() -> None:
    with (
        patch(
            "punt_lux.ptyd.terminal_child.time.monotonic", return_value=10.0
        ) as clock,
        patch(
            "punt_lux.ptyd.terminal_child.time.sleep",
            side_effect=AssertionError("blocking"),
        ),
        patch("punt_lux.ptyd.terminal_child.os.killpg") as killpg,
        patch(
            "punt_lux.ptyd.terminal_child.os.kill",
            side_effect=AssertionError("PID signal"),
        ),
        patch(
            "punt_lux.ptyd.terminal_child.os.waitpid",
            return_value=(123, signal.SIGKILL),
        ) as wait,
    ):
        child = TerminalChild(123)
        child.stop()
        child.stop()
        assert not child.poll()
        killpg.assert_called_once_with(123, signal.SIGHUP)
        wait.assert_not_called()
        clock.return_value = 10.31
        assert child.poll()
        killpg.assert_called_with(123, signal.SIGKILL)
        wait.assert_called_once_with(123, os.WNOHANG)
        assert child.exit_code == -signal.SIGKILL
        child.stop()
        assert child.poll()
        assert killpg.call_count == 2


def test_exited_leader_stays_unreaped_until_descendants_are_signalled() -> None:
    status = SimpleNamespace(si_status=7, si_code=os.CLD_EXITED)
    with (
        patch(
            "punt_lux.ptyd.terminal_child.time.monotonic", return_value=10.0
        ) as clock,
        patch("punt_lux.ptyd.terminal_child.os.waitid", return_value=status) as peek,
        patch(
            "punt_lux.ptyd.terminal_child.os.waitpid", return_value=(123, 7 << 8)
        ) as reap,
        patch("punt_lux.ptyd.terminal_child.os.killpg") as killpg,
    ):
        child = TerminalChild(123)
        assert not child.poll()
        peek.assert_called_once_with(
            os.P_PID, 123, os.WEXITED | os.WNOHANG | os.WNOWAIT
        )
        reap.assert_not_called()
        assert child.exit_code == 7
        assert not child.reaped
        clock.return_value = 10.31
        assert child.poll()
        assert [call.args[1] for call in killpg.call_args_list] == [
            signal.SIGHUP,
            signal.SIGKILL,
        ]


def test_missing_group_still_reaps_owned_child() -> None:
    with (
        patch("punt_lux.ptyd.terminal_child.os.killpg", side_effect=ProcessLookupError),
        patch("punt_lux.ptyd.terminal_child.os.waitpid", return_value=(123, 0)),
    ):
        child = TerminalChild(123)
        child.stop(grace_s=0)
        assert child.poll()


def test_permission_errors_are_not_hidden() -> None:
    with (
        patch("punt_lux.ptyd.terminal_child.os.killpg", side_effect=PermissionError),
        pytest.raises(PermissionError),
    ):
        TerminalChild(123).stop()


@pytest.mark.parametrize("pid", [-1, 0, True])
def test_invalid_pid_is_rejected(pid: int) -> None:
    with pytest.raises(ValueError):
        TerminalChild(pid)


def test_menu_lifetime_still_signals_only_its_owned_pid() -> None:
    with (
        patch("punt_lux.ptyd.child.os.waitpid", side_effect=[(0, 0), (123, 0)]),
        patch("punt_lux.ptyd.child.os.kill") as kill,
        patch(
            "punt_lux.ptyd.child.os.killpg",
            side_effect=AssertionError("menu group signal"),
        ),
    ):
        ChildLifetime(123).stop()
        kill.assert_called_once_with(123, signal.SIGHUP)
