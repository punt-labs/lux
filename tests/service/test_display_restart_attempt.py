"""One restart captures its old PID and stderr freshness boundary together."""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from punt_lux.service import DISPLAY_SPEC, ServiceActionFailedError
from punt_lux.service._display_restart_attempt import RestartAttempt
from punt_lux.service.display_restart import DisplayRestart, DisplayRestartError


@pytest.mark.parametrize("pid", [None, 501])
def test_capture_existing_and_fresh_install_processes(pid: int | None) -> None:
    with (
        patch("punt_lux.service._backends.pgrep_pid", return_value=pid),
        patch("punt_lux.service._display_restart_attempt.time.time", return_value=10),
    ):
        attempt = RestartAttempt.start(DISPLAY_SPEC, 30)
    assert attempt.before == pid
    assert attempt.started_at == 10
    assert attempt.wait == 30
    assert attempt.spec is DISPLAY_SPEC


def test_initial_process_timeout_is_a_logged_service_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with (
        patch(
            "punt_lux.service._backends.pgrep_pid",
            side_effect=subprocess.TimeoutExpired("pgrep", 2),
        ),
        pytest.raises(ServiceActionFailedError, match="cannot inspect Display"),
    ):
        RestartAttempt.start(DISPLAY_SPEC, 30)
    assert DISPLAY_SPEC.launchd_label in caplog.text


def test_real_lookup_timeout_is_never_a_fresh_install() -> None:
    with (
        patch(
            "punt_lux.service._backends.subprocess.run",
            side_effect=subprocess.TimeoutExpired("pgrep", 2),
        ),
        pytest.raises(ServiceActionFailedError, match="cannot inspect Display"),
    ):
        RestartAttempt.start(DISPLAY_SPEC, 30)


def test_poll_lookup_timeout_is_not_a_missing_process() -> None:
    manager = MagicMock()
    with (
        patch(
            "punt_lux.service._backends.subprocess.run",
            side_effect=[
                subprocess.CompletedProcess("pgrep", 0, stdout=b"501\n"),
                subprocess.TimeoutExpired("pgrep", 2),
            ],
        ),
        patch.object(DisplayRestart, "_polls", return_value=iter([None])),
        pytest.raises(DisplayRestartError, match=r"pgrep.*timed out"),
    ):
        DisplayRestart(manager=manager, paths=MagicMock()).run()
    manager.restart.assert_called_once()
