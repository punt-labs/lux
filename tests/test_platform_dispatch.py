"""Tests for platform_classes -- explicit validation of the platform key."""

from __future__ import annotations

import pytest

from punt_lux._backend_launchd import LaunchdBackend
from punt_lux._backend_systemd import SystemdBackend
from punt_lux._legacy_sweep_launchd import LaunchdLegacySweep
from punt_lux._legacy_sweep_systemd import SystemdLegacySweep
from punt_lux._platform_dispatch import platform_classes


def test_macos_resolves_launchd_classes() -> None:
    classes = platform_classes("macos")
    assert classes.backend is LaunchdBackend
    assert classes.legacy_sweep is LaunchdLegacySweep


def test_linux_resolves_systemd_classes() -> None:
    classes = platform_classes("linux")
    assert classes.backend is SystemdBackend
    assert classes.legacy_sweep is SystemdLegacySweep


def test_unknown_platform_raises_value_error() -> None:
    with pytest.raises(ValueError, match="Unsupported platform"):
        platform_classes("windows")
