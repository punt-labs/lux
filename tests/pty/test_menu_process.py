"""Supervisor failures stay outside native owner; operator stop prevents restart."""

from __future__ import annotations

import logging
from unittest.mock import Mock

import pytest

from punt_lux.pty.menu_process import MenuProcess


def test_helper_failure_is_bounded_and_does_not_escape_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = [0.0]
    spawn = Mock(side_effect=OSError("process limit"))
    monkeypatch.setattr("punt_lux.pty.menu_process.time.monotonic", lambda: now[0])
    monkeypatch.setattr("punt_lux.pty.menu_process.os.posix_spawn", spawn)
    helper = MenuProcess()
    helper.start()
    helper.poll()
    assert spawn.call_count == 1
    now[0] = 6
    helper.poll()
    assert spawn.call_count == 2
    helper.close()
    now[0] = 12
    helper.poll()
    assert spawn.call_count == 2


def test_helper_is_observed_without_blocking_or_restarting_while_live(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child = Mock()
    child.poll.return_value = False
    spawn = Mock(return_value=123)
    monkeypatch.setattr("punt_lux.pty.menu_process.os.posix_spawn", spawn)

    def held(_pid: int) -> Mock:
        return child

    monkeypatch.setattr("punt_lux.pty.menu_process.ChildLifetime", held)
    helper = MenuProcess()
    helper.start()
    helper.poll()
    assert spawn.call_count == 1
    assert "setsid" not in spawn.call_args.kwargs
    helper.close()
    child.stop.assert_called_once_with()


def test_exited_helper_logs_upgrade_guidance_once_before_retry(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    now = [0.0]
    child = Mock(exit_code=1)
    child.poll.return_value = True
    spawn = Mock(return_value=123)
    monkeypatch.setattr("punt_lux.pty.menu_process.time.monotonic", lambda: now[0])
    monkeypatch.setattr("punt_lux.pty.menu_process.os.posix_spawn", spawn)
    monkeypatch.setattr(
        "punt_lux.pty.menu_process.ChildLifetime", Mock(return_value=child)
    )
    helper = MenuProcess()
    helper.start()
    helper.poll()
    helper.poll()
    assert len(caplog.records) == 1
    assert "exited (status 1)" in caplog.text
    assert "restart luxd-pty with make restart" in caplog.text
    assert spawn.call_count == 1
    now[0] = 5
    helper.poll()
    assert spawn.call_count == 2


@pytest.mark.parametrize(
    ("exit_code", "level"),
    [(0, logging.INFO), (None, logging.WARNING), (-15, logging.ERROR)],
)
def test_helper_exit_severity(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    exit_code: int | None,  # Another waiter may reap without providing status.
    level: int,
) -> None:
    caplog.set_level(logging.INFO)
    child = Mock(exit_code=exit_code)
    child.poll.return_value = True
    monkeypatch.setattr(
        "punt_lux.pty.menu_process.os.posix_spawn", Mock(return_value=123)
    )
    monkeypatch.setattr(
        "punt_lux.pty.menu_process.ChildLifetime", Mock(return_value=child)
    )
    helper = MenuProcess()
    helper.start()
    helper.poll()
    assert len(caplog.records) == 1
    assert caplog.records[0].levelno == level


def test_intentional_stop_does_not_log_a_helper_failure(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    child = Mock(exit_code=-15)
    child.poll.return_value = True
    monkeypatch.setattr(
        "punt_lux.pty.menu_process.os.posix_spawn", Mock(return_value=123)
    )
    monkeypatch.setattr(
        "punt_lux.pty.menu_process.ChildLifetime", Mock(return_value=child)
    )
    helper = MenuProcess()
    helper.start()
    helper.request_stop()
    helper.poll()
    helper.close()
    assert not caplog.records
    child.stop.assert_called_once_with()
