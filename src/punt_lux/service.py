"""Daemon lifecycle for hub and display services via launchd/systemd."""

from __future__ import annotations

import logging
import os
import platform
from typing import ClassVar, Self, final

from punt_lux._backend_launchd import LaunchdBackend
from punt_lux._backend_systemd import SystemdBackend
from punt_lux._backends import ServiceBackend, has_linger
from punt_lux._service_errors import (
    ServiceActionFailedError,
    ServiceNotInstalledError,
)
from punt_lux._service_spec import DISPLAY_SPEC, HUB_SPEC, ServiceSpec

logger = logging.getLogger(__name__)

__all__ = [
    "DISPLAY_SPEC",
    "HUB_SPEC",
    "DisplayServiceManager",
    "HubServiceManager",
    "ServiceActionFailedError",
    "ServiceManager",
    "ServiceNotInstalledError",
    "ServiceSpec",
    "detect_platform",
]


def detect_platform() -> str:
    """Return ``'macos'`` or ``'linux'``. Raise on unsupported platforms."""
    system = platform.system()
    if system == "Darwin":
        return "macos"
    if system == "Linux":
        return "linux"
    msg = f"Unsupported platform: {system}; only macOS and Linux are supported."
    raise SystemExit(msg)


class ServiceManager:
    """Coordinate one service's lifecycle; subclasses fix ``_SPEC``."""

    _SPEC: ClassVar[ServiceSpec]

    __slots__ = ("_backend",)
    _backend: ServiceBackend

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        backend_cls = LaunchdBackend if detect_platform() == "macos" else SystemdBackend
        self._backend = backend_cls(cls._SPEC)
        return self

    @classmethod
    def for_hub(cls) -> HubServiceManager:
        """Return a manager supervising luxd (the session hub)."""
        return HubServiceManager()

    @classmethod
    def for_display(cls) -> DisplayServiceManager:
        """Return a manager supervising the display window process."""
        return DisplayServiceManager()

    def install(self) -> str:
        """Install the service and return a status message."""
        self._backend.install()
        is_running = self._backend.is_active()
        exec_display = " ".join(self._SPEC.resolve_exec_args())
        status_label = "running" if is_running else "installed (not yet running)"
        lines = [
            f"{self._SPEC.display_name} {status_label}.",
            f"  Service: {self._backend.config_path()}",
            f"  Command: {exec_display}",
        ]
        if isinstance(self._backend, SystemdBackend) and not has_linger():
            lines.append(
                "  Warning: loginctl linger is not enabled. "
                "The service will stop when you log out. "
                "Run: loginctl enable-linger"
            )
        return os.linesep.join(lines)

    def uninstall(self) -> str:
        """Remove the service and return a status message."""
        path = self._backend.config_path()
        self._backend.uninstall()
        return f"{self._SPEC.display_name} uninstalled. Removed {path}."

    def stop(self) -> str:
        """Stop the service; raise if the supervisor call itself failed."""
        if not self._backend.stop():
            msg = (
                f"{self._SPEC.display_name} stop failed. See "
                "~/.punt-labs/lux/logs/ for details."
            )
            raise ServiceActionFailedError(msg)
        return f"{self._SPEC.display_name} stopped."

    def start(self) -> str:
        """Start an already-installed, stopped service."""
        if not self._backend.config_path().exists():
            msg = (
                f"{self._SPEC.display_name} is not installed. "
                f"Run 'lux {self._SPEC.cli_verb} install' first."
            )
            raise ServiceNotInstalledError(msg)
        if not self._backend.start():
            msg = (
                f"{self._SPEC.display_name} start failed. See "
                "~/.punt-labs/lux/logs/ for details."
            )
            raise ServiceActionFailedError(msg)
        return f"{self._SPEC.display_name} started."

    @property
    def is_active(self) -> bool:
        """Return whether the service is currently running."""
        return self._backend.is_active()

    @property
    def spec(self) -> ServiceSpec:
        """Return the spec identifying this managed service."""
        return self._SPEC


@final
class HubServiceManager(ServiceManager):
    """Supervise luxd (the session hub) under launchd/systemd."""

    __slots__ = ()
    _SPEC: ClassVar[ServiceSpec] = HUB_SPEC


@final
class DisplayServiceManager(ServiceManager):
    """Supervise the ImGui display window process under launchd/systemd."""

    __slots__ = ()
    _SPEC: ClassVar[ServiceSpec] = DISPLAY_SPEC
