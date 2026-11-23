"""One restart captures its old PID and stderr freshness boundary together."""

from __future__ import annotations

import subprocess
from unittest.mock import patch

import pytest

from punt_lux.service import DISPLAY_SPEC, ServiceActionFailedError
from punt_lux.service._display_restart_attempt import RestartAttempt


@pytest.mark.parametrize("pid", [None, 501])
def test_capture_existing_and_fresh_install_processes(pid: int | None) -> None:
    with (
        patch("punt_lux.service._backends.pgrep_pid", return_value=pid),
        patch("punt_lux.service._display_restart_attempt.time.time", return_value=10),
    ):
        attempt = RestartAttempt.capture(DISPLAY_SPEC, 30)
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
        RestartAttempt.capture(DISPLAY_SPEC, 30)
    assert DISPLAY_SPEC.launchd_label in caplog.text
