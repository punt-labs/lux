"""Keep failed plist upgrades explicit without destructive recovery attempts."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from punt_lux.service import DISPLAY_SPEC, HUB_SPEC
from punt_service import ServiceMigrationError, ServiceSpec
from punt_service._backend_launchd import LaunchdBackend


@pytest.mark.parametrize("spec", [DISPLAY_SPEC, HUB_SPEC])
def test_leading_whitespace_does_not_restart_an_active_service(
    spec: ServiceSpec, tmp_path: Path
) -> None:
    with (
        patch("pathlib.Path.home", return_value=tmp_path),
        patch.object(ServiceSpec, "resolve_exec_args", return_value=["/bin/service"]),
        patch.object(LaunchdBackend, "is_active", return_value=True),
        patch("punt_service._launchctl.subprocess.run") as run,
    ):
        backend = LaunchdBackend(spec)
        path = backend.config_path()
        path.parent.mkdir(parents=True)
        previous = "\n   \t" + backend._plist_content()
        path.write_text(previous)

        assert backend.install() is True

    run.assert_not_called()
    assert path.read_text() == previous


@pytest.mark.parametrize("spec", [DISPLAY_SPEC, HUB_SPEC])
@pytest.mark.parametrize("active", [False, True])
def test_failed_bootstrap_logs_label_and_retains_new_plist(
    spec: ServiceSpec,
    active: bool,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with (
        patch("pathlib.Path.home", return_value=tmp_path),
        patch.object(
            LaunchdBackend, "_plist_content", return_value="replacement plist"
        ),
        patch.object(LaunchdBackend, "is_active", return_value=active),
        patch("punt_service._launchctl.subprocess.run") as run,
        caplog.at_level(logging.ERROR),
    ):
        backend = LaunchdBackend(spec)
        path = backend.config_path()
        path.parent.mkdir(parents=True)
        path.write_text("previous plist")
        failure = subprocess.CompletedProcess([], 5, stdout="", stderr="I/O error")
        run.side_effect = (
            [
                subprocess.CompletedProcess([], 0, stdout="", stderr=""),
                subprocess.CompletedProcess([], 0, stdout="", stderr=""),
                subprocess.CompletedProcess([], 113, stdout="", stderr=""),
                failure,
            ]
            if active
            else [failure]
        )
        with pytest.raises(
            ServiceMigrationError, match=f"failed to bootstrap {spec.launchd_label}"
        ):
            backend.install()

    assert path.read_text() == "replacement plist"
    assert spec.launchd_label in caplog.text
    assert str(path) in caplog.text
    assert "launchd registration is not guaranteed" in caplog.text
    assert [call.args[0][1] for call in run.call_args_list] == (
        ["print", "bootout", "print", "bootstrap"] if active else ["bootstrap"]
    )


def test_successful_bootstrap_does_not_log_failure(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with (
        patch("pathlib.Path.home", return_value=tmp_path),
        patch.object(LaunchdBackend, "_plist_content", return_value="new plist"),
        patch.object(LaunchdBackend, "is_active", return_value=False),
        patch("punt_service._launchctl.subprocess.run") as run,
        caplog.at_level(logging.ERROR),
    ):
        run.return_value = subprocess.CompletedProcess([], 0, stdout="", stderr="")
        assert LaunchdBackend(DISPLAY_SPEC).install() is False

    assert not caplog.records
    assert [call.args[0][1] for call in run.call_args_list] == ["bootstrap"]
