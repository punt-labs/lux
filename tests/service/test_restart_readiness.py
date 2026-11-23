"""Bound supervisor observations without masking the original readiness failure."""

from __future__ import annotations

import logging
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from punt_lux.service import DISPLAY_SPEC, HUB_SPEC, ServiceSpec
from punt_lux.service._restart_readiness import RestartReadiness
from punt_lux.service.display_restart import DisplayRestart, DisplayRestartError
from punt_lux.service.hub_restart import HubRestart, HubRestartError


@pytest.mark.parametrize("spec", [DISPLAY_SPEC, HUB_SPEC])
@pytest.mark.parametrize("returncode", [0, 113, 5])
def test_failure_logs_label_and_launchctl_status(
    spec: ServiceSpec, returncode: int, caplog: pytest.LogCaptureFixture
) -> None:
    with (
        patch(
            "punt_lux.service._restart_readiness.platform.system", return_value="Darwin"
        ),
        patch("punt_lux.service._restart_readiness.subprocess.run") as run,
        caplog.at_level(logging.ERROR),
    ):
        run.return_value = subprocess.CompletedProcess([], returncode)
        RestartReadiness.failure(spec, "readiness timed out")

    assert spec.launchd_label in caplog.text
    assert "readiness timed out" in caplog.text
    assert f"rc={returncode}" in caplog.text
    run.assert_called_once_with(
        ["launchctl", "list", spec.launchd_label],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
        timeout=2.0,
    )


@pytest.mark.parametrize(
    "error,diagnostic",
    [
        (subprocess.TimeoutExpired("launchctl", 2), "timed out after 2s"),
        (FileNotFoundError("private detail"), "unavailable (FileNotFoundError)"),
        (PermissionError("private detail"), "unavailable (PermissionError)"),
    ],
)
def test_observation_failure_is_logged_without_raising(
    error: OSError | subprocess.TimeoutExpired,
    diagnostic: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with (
        patch(
            "punt_lux.service._restart_readiness.platform.system", return_value="Darwin"
        ),
        patch("punt_lux.service._restart_readiness.subprocess.run", side_effect=error),
        caplog.at_level(logging.ERROR),
    ):
        RestartReadiness.failure(DISPLAY_SPEC, "original failure")

    assert "original failure" in caplog.text
    assert diagnostic in caplog.text
    assert "private detail" not in caplog.text


def test_other_platforms_log_failure_without_launchctl(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with (
        patch(
            "punt_lux.service._restart_readiness.platform.system", return_value="Linux"
        ),
        patch("punt_lux.service._restart_readiness.subprocess.run") as run,
        caplog.at_level(logging.ERROR),
    ):
        RestartReadiness.failure(HUB_SPEC, "not ready")

    run.assert_not_called()
    assert HUB_SPEC.launchd_label in caplog.text
    assert "launchd state unavailable on this platform" in caplog.text


@pytest.mark.parametrize("wait,count", [(0, 0), (1, 2)])
def test_polls_retain_bounded_delays(wait: float, count: int) -> None:
    with patch("punt_lux.service._restart_readiness.time.sleep") as sleep:
        assert list(RestartReadiness.polls(wait, 0.5)) == [None] * count
    assert sleep.call_count == count


@pytest.mark.parametrize(
    "restart,error,spec,module",
    [
        (DisplayRestart, DisplayRestartError, DISPLAY_SPEC, "display_restart"),
        (HubRestart, HubRestartError, HUB_SPEC, "hub_restart"),
    ],
)
def test_timeout_logs_before_raising_original_error(
    restart: type[DisplayRestart] | type[HubRestart],
    error: type[DisplayRestartError] | type[HubRestartError],
    spec: ServiceSpec,
    module: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    manager = MagicMock()
    with (
        patch(f"punt_lux.service.{module}.pgrep_pid", return_value=None),
        patch.object(restart, "_polls", return_value=iter(())),
        patch(
            "punt_lux.service._restart_readiness.platform.system", return_value="Darwin"
        ),
        patch("punt_lux.service._restart_readiness.subprocess.run") as run,
        caplog.at_level(logging.ERROR),
    ):
        run.return_value = subprocess.CompletedProcess([], 113)
        with pytest.raises(error, match="did not come back"):
            restart(manager=manager, paths=MagicMock()).run()
        assert spec.launchd_label in caplog.text
        assert "did not come back within 30s" in caplog.text
        assert "rc=113" in caplog.text
    manager.restart.assert_called_once_with()


@pytest.mark.parametrize(
    "restart,spec,module",
    [
        (DisplayRestart, DISPLAY_SPEC, "display_restart"),
        (HubRestart, HUB_SPEC, "hub_restart"),
    ],
)
def test_success_does_not_probe_launchd(
    restart: type[DisplayRestart] | type[HubRestart],
    spec: ServiceSpec,
    module: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    paths = MagicMock()
    paths.peer_pid.return_value = 102
    with (
        patch(f"punt_lux.service.{module}.pgrep_pid", side_effect=[101, 102]),
        patch.object(restart, "_polls", return_value=iter([None])),
        patch("punt_lux.service._restart_readiness.subprocess.run") as run,
        caplog.at_level(logging.ERROR),
    ):
        assert "pid 102" in restart(manager=MagicMock(), paths=paths).run()
    run.assert_not_called()
    assert not caplog.records
