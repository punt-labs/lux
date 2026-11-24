"""A third-party daemon reuses Lux's supervisor configuration and install path."""

from __future__ import annotations

import plistlib
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from punt_service import ServiceSpec
from punt_service._backend_launchd import LaunchdBackend
from punt_service._backend_systemd import SystemdBackend

_FOOD = ServiceSpec(
    display_name="food",
    launchd_label="com.example.food",
    systemd_unit="food",
    systemd_description="Example food daemon",
    binary_name="food",
    extra_args=("--flavour", "sweet & sour"),
    cli_verb="food",
    process_name="food",
)


def test_non_lux_spec_installs_through_both_backends(tmp_path: Path) -> None:
    binary = tmp_path / ".local/bin/food"
    binary.parent.mkdir(parents=True)
    binary.touch()
    with (
        patch("pathlib.Path.home", return_value=tmp_path),
        patch(
            "punt_service._launchctl.subprocess.run",
            return_value=Mock(returncode=0),
        ),
        patch.object(LaunchdBackend, "is_active", return_value=False),
    ):
        launchd = LaunchdBackend(_FOOD)
        systemd = SystemdBackend(_FOOD)
        assert launchd.install() is False
        assert systemd.install() is False
        plist = plistlib.loads(launchd.config_path().read_bytes())
        assert plist["Label"] == "com.example.food"
        assert plist["ProgramArguments"] == [str(binary), "--flavour", "sweet & sour"]
        unit = systemd.config_path().read_text()
        assert "Description=Example food daemon" in unit
        assert f'ExecStart="{binary}" "--flavour" "sweet & sour"' in unit
        assert systemd.config_path().name == "food.service"


def test_non_lux_spec_names_the_missing_binary(tmp_path: Path) -> None:
    with (
        patch("pathlib.Path.home", return_value=tmp_path),
        pytest.raises(RuntimeError, match="Cannot find food binary"),
    ):
        _FOOD.resolve_exec_args()
