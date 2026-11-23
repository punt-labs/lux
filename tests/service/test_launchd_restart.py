"""Recover only missing launchd registrations and retain normal readiness checks."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from punt_lux.service import (
    DISPLAY_SPEC,
    HUB_SPEC,
    ServiceManager,
    ServiceNotInstalledError,
    ServiceSpec,
)
from punt_lux.service._backend_launchd import LaunchdBackend
from punt_lux.service.display_restart import DisplayRestart
from punt_lux.service.hub_restart import HubRestart
from tests.service._probe_double import ProbeDouble


@pytest.mark.parametrize("spec", [DISPLAY_SPEC, HUB_SPEC])
@pytest.mark.parametrize(
    "kick_rc,installed,bootstrap_rc,expected,verbs",
    [
        (0, True, 0, True, ["kickstart"]),
        (113, True, 0, True, ["kickstart", "bootstrap"]),
        (113, True, 5, False, ["kickstart", "bootstrap"]),
        (113, False, 0, False, ["kickstart"]),
        (5, True, 0, False, ["kickstart"]),
        (1, True, 0, False, ["kickstart"]),
    ],
)
def test_restart_recovery_partitions(
    spec: ServiceSpec,
    kick_rc: int,
    installed: bool,
    bootstrap_rc: int,
    expected: bool,
    verbs: list[str],
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with (
        patch("pathlib.Path.home", return_value=tmp_path),
        patch("punt_lux.service._launchctl.subprocess.run") as run,
        caplog.at_level(logging.INFO),
    ):
        backend = LaunchdBackend(spec)
        path = backend.config_path()
        if installed:
            path.parent.mkdir(parents=True)
            path.write_text("existing plist")
        run.side_effect = [
            subprocess.CompletedProcess(
                [], kick_rc, stdout="", stderr="kickstart error"
            ),
            subprocess.CompletedProcess(
                [], bootstrap_rc, stdout="", stderr="bootstrap error"
            ),
        ]
        assert backend.restart() is expected
        assert [call.args[0][1] for call in run.call_args_list] == verbs
        if "bootstrap" in verbs:
            assert run.call_args.args[0][-1] == str(path)
            assert spec.launchd_label in caplog.text
            assert str(path) in caplog.text
            assert "bootstrapping installed plist" in caplog.text
            attempt = next(
                record
                for record in caplog.records
                if "bootstrapping installed plist" in record.getMessage()
            )
            assert attempt.levelno == logging.WARNING
            if bootstrap_rc:
                assert any(
                    record.levelno >= logging.WARNING
                    and "launchctl bootstrap failed" in record.getMessage()
                    for record in caplog.records
                )
        if kick_rc == 0:
            assert not caplog.records
        else:
            failures = [
                record
                for record in caplog.records
                if "launchctl kickstart failed" in record.getMessage()
            ]
            assert len(failures) == 1
            expected_level = logging.INFO if "bootstrap" in verbs else logging.WARNING
            assert failures[0].levelno == expected_level
        if installed:
            assert path.read_text() == "existing plist"


@pytest.mark.parametrize("display", [False, True])
def test_missing_plist_still_fails_before_supervisor_call(
    display: bool, tmp_path: Path
) -> None:
    with (
        patch("pathlib.Path.home", return_value=tmp_path),
        patch("punt_lux.service.detect_platform", return_value="macos"),
        patch("punt_lux.service._launchctl.subprocess.run") as run,
    ):
        manager = ServiceManager.for_display() if display else ServiceManager.for_hub()
        with pytest.raises(ServiceNotInstalledError):
            manager.restart()
    run.assert_not_called()


@pytest.mark.parametrize(
    "restart,spec,module",
    [
        (DisplayRestart, DISPLAY_SPEC, "display_restart"),
        (HubRestart, HUB_SPEC, "hub_restart"),
    ],
)
def test_recovered_restart_waits_for_readiness(
    restart: type[DisplayRestart] | type[HubRestart],
    spec: ServiceSpec,
    module: str,
    tmp_path: Path,
) -> None:
    paths = MagicMock()
    paths.peer_pid.return_value = 102
    with (
        patch(
            "punt_lux.service._readiness_probe.ReadinessProbe.local",
            autospec=True,
            side_effect=ProbeDouble.local,
        ),
        patch("pathlib.Path.home", return_value=tmp_path),
        patch("punt_lux.service.detect_platform", return_value="macos"),
        patch("punt_lux.service._launchctl.subprocess.run") as run,
        patch(
            "punt_lux.service._backends.pgrep_pid"
            if module == "display_restart"
            else f"punt_lux.service.{module}.pgrep_pid",
            side_effect=[101, 102],
        ),
        patch.object(restart, "_polls", return_value=iter([None])),
        patch(
            "punt_lux.service._hub_display_probe.HubDisplayProbe.connected",
            return_value=True,
        ),
        patch("punt_lux.service._display_readiness._STABILITY_SECONDS", 0),
    ):
        path = tmp_path / "Library/LaunchAgents" / f"{spec.launchd_label}.plist"
        path.parent.mkdir(parents=True)
        path.write_text("existing plist")
        run.side_effect = [
            subprocess.CompletedProcess([], 113, stdout="", stderr="not found"),
            subprocess.CompletedProcess([], 0, stdout="", stderr=""),
        ]
        assert "pid 102" in restart(paths=paths).run()
    assert [call.args[0][1] for call in run.call_args_list] == [
        "kickstart",
        "bootstrap",
    ]
