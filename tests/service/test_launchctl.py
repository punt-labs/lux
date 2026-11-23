"""Record successful launchd unload requests without logging false unloads."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from punt_lux.service import DISPLAY_SPEC, HUB_SPEC, ServiceSpec
from punt_lux.service._backend_launchd import LaunchdBackend
from punt_lux.service._launchctl import launchctl
from punt_lux.service._legacy_sweep_launchd import LaunchdLegacySweep


@pytest.mark.parametrize("spec", [DISPLAY_SPEC, HUB_SPEC])
@pytest.mark.parametrize("action", ["stop", "uninstall"])
def test_backend_unloads_log_the_exact_target(
    spec: ServiceSpec,
    action: str,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with (
        patch("pathlib.Path.home", return_value=tmp_path),
        patch("punt_lux.service._launchctl.os.getuid", return_value=501),
        patch("punt_lux.service._launchctl.subprocess.run") as run,
        caplog.at_level(logging.INFO),
    ):
        backend = LaunchdBackend(spec)
        path = backend.config_path()
        path.parent.mkdir(parents=True)
        path.write_text("installed plist")
        run.return_value = subprocess.CompletedProcess([], 0, stdout="", stderr="")
        getattr(backend, action)()
    assert f"bootout succeeded for gui/501/{spec.launchd_label}" in caplog.text
    assert path.exists() is (action == "stop")
    run.assert_called_once_with(
        ["launchctl", "bootout", f"gui/501/{spec.launchd_label}"],
        capture_output=True,
        text=True,
        check=False,
    )


def test_upgrade_sweep_bootout_logs_target(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with (
        patch("punt_lux.service._launchctl.os.getuid", return_value=501),
        patch.object(LaunchdLegacySweep, "_is_label_clean", return_value=False),
        patch.object(
            LaunchdLegacySweep, "_plist_path", return_value=tmp_path / "retired.plist"
        ),
        patch.object(LaunchdLegacySweep, "_wait_until_deregistered", return_value=True),
        patch("punt_lux.service._launchctl.subprocess.run") as run,
        caplog.at_level(logging.INFO),
    ):
        run.return_value = subprocess.CompletedProcess([], 0, stdout="", stderr="")
        LaunchdLegacySweep(HUB_SPEC)._sweep_one(HUB_SPEC.launchd_label)
    assert f"bootout succeeded for gui/501/{HUB_SPEC.launchd_label}" in caplog.text


def test_missing_plist_stop_does_not_claim_a_bootout(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with (
        patch("pathlib.Path.home", return_value=tmp_path),
        patch("punt_lux.service._launchctl.subprocess.run") as run,
        caplog.at_level(logging.INFO),
    ):
        assert LaunchdBackend(DISPLAY_SPEC).stop()
    run.assert_not_called()
    assert "bootout succeeded" not in caplog.text


@pytest.mark.parametrize("returncode", [113, 5])
@pytest.mark.parametrize("probe", [False, True])
def test_failed_bootout_never_logs_success(
    returncode: int, probe: bool, caplog: pytest.LogCaptureFixture
) -> None:
    with (
        patch("punt_lux.service._launchctl.subprocess.run") as run,
        caplog.at_level(logging.INFO),
    ):
        run.return_value = subprocess.CompletedProcess(
            [], returncode, stdout="", stderr="not unloaded"
        )
        invoke = launchctl.probe if probe else launchctl.run
        assert not invoke(["launchctl", "bootout", "gui/501/example"], verb="bootout")
    assert "succeeded" not in caplog.text
    assert bool(caplog.records) is not (probe and returncode == 113)


@pytest.mark.parametrize("verb", ["print", "bootstrap", "kickstart"])
def test_other_successes_do_not_claim_an_unload(
    verb: str, caplog: pytest.LogCaptureFixture
) -> None:
    with (
        patch("punt_lux.service._launchctl.subprocess.run") as run,
        caplog.at_level(logging.INFO),
    ):
        run.return_value = subprocess.CompletedProcess([], 0, stdout="", stderr="")
        assert launchctl.run(["launchctl", verb, "gui/501/example"], verb=verb)
    assert not caplog.records
