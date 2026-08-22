"""Platform-keyed lookup: which backend and legacy-sweep class to compose."""

from __future__ import annotations

import platform
from typing import TYPE_CHECKING, NamedTuple

from punt_lux._backend_launchd import LaunchdBackend
from punt_lux._backend_systemd import SystemdBackend
from punt_lux._legacy_sweep_launchd import LaunchdLegacySweep
from punt_lux._legacy_sweep_systemd import SystemdLegacySweep

if TYPE_CHECKING:
    from collections.abc import Callable

    from punt_lux._backends import ServiceBackend
    from punt_lux._legacy_sweep import LegacySweep
    from punt_lux._service_spec import ServiceSpec

__all__ = ["PlatformClasses", "detect_platform", "platform_classes"]

# Each field is a constructor callable, not `type[X]` -- ServiceBackend and
# LegacySweep are declared without their concrete subclasses' `__new__(cls,
# spec)` signature (a Protocol/ABC carries no constructor contract), so
# `type[X]` would type-check as the zero-arg base constructor instead.


def detect_platform() -> str:
    """Return ``'macos'`` or ``'linux'``. Raise on unsupported platforms."""
    system = platform.system()
    if system == "Darwin":
        return "macos"
    if system == "Linux":
        return "linux"
    msg = f"Unsupported platform: {system}; only macOS and Linux are supported."
    raise SystemExit(msg)


class PlatformClasses(NamedTuple):
    """The backend and legacy-sweep classes composed for one platform."""

    backend: Callable[[ServiceSpec], ServiceBackend]
    legacy_sweep: Callable[[ServiceSpec], LegacySweep]


def platform_classes(platform: str) -> PlatformClasses:
    """Return the classes for ``platform`` (``"macos"`` or ``"linux"``)."""
    if platform == "macos":
        return PlatformClasses(LaunchdBackend, LaunchdLegacySweep)
    if platform == "linux":
        return PlatformClasses(SystemdBackend, SystemdLegacySweep)
    msg = f"Unsupported platform: {platform!r}; only 'macos' and 'linux' are supported."
    raise ValueError(msg)
