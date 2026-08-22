"""Daemon lifecycle for hub and display services via launchd/systemd."""

from __future__ import annotations

import logging
import os
from typing import ClassVar, Self, final

from punt_lux._backends import ServiceBackend
from punt_lux._doctor_result import DoctorResult
from punt_lux._legacy_sweep import LegacySweep
from punt_lux._platform_dispatch import detect_platform, platform_classes
from punt_lux._port_guard import PortGuard
from punt_lux._service_errors import (
    PortConflictError,
    ServiceActionFailedError,
    ServiceMigrationError,
    ServiceNotInstalledError,
)
from punt_lux._service_spec import DISPLAY_SPEC, HUB_SPEC, ServiceSpec

logger = logging.getLogger(__name__)

__all__ = [
    "DISPLAY_SPEC",
    "HUB_SPEC",
    "DisplayServiceManager",
    "DoctorResult",
    "HubServiceManager",
    "PortConflictError",
    "ServiceActionFailedError",
    "ServiceManager",
    "ServiceMigrationError",
    "ServiceNotInstalledError",
    "ServiceSpec",
    "detect_platform",
]


class ServiceManager:
    """Coordinate one service's lifecycle; subclasses fix ``_SPEC``."""

    _SPEC: ClassVar[ServiceSpec]

    __slots__ = ("_backend", "_legacy_sweep", "_port_guard")
    _backend: ServiceBackend
    _legacy_sweep: LegacySweep
    _port_guard: PortGuard

    def __init_subclass__(cls, **kwargs: object) -> None:
        """Reject a subclass that forgets to fix ``_SPEC``, at definition time."""
        super().__init_subclass__(**kwargs)
        if "_SPEC" not in cls.__dict__:
            msg = (
                f"{cls.__name__} must set _SPEC "
                "(see HubServiceManager, DisplayServiceManager)"
            )
            raise TypeError(msg)

    def __new__(cls) -> Self:
        if "_SPEC" not in cls.__dict__:
            msg = (
                f"{cls.__name__} is abstract — instantiate HubServiceManager or "
                "DisplayServiceManager (or use for_hub()/for_display())"
            )
            raise TypeError(msg)
        self = super().__new__(cls)
        classes = platform_classes(detect_platform())
        self._backend = classes.backend(cls._SPEC)
        self._legacy_sweep = classes.legacy_sweep(cls._SPEC)
        self._port_guard = PortGuard(cls._SPEC)
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
        """Cure any legacy registration and port conflict, then install."""
        self._legacy_sweep.sweep()
        if self._SPEC.health_port is not None:
            self._port_guard.guard()
        self._backend.install()
        is_running = self._backend.is_active()
        exec_display = " ".join(self._SPEC.resolve_exec_args())
        status_label = "running" if is_running else "installed (not yet running)"
        lines = [
            f"{self._SPEC.display_name} {status_label}.",
            f"  Service: {self._backend.config_path()}",
            f"  Command: {exec_display}",
        ]
        if warning := self._backend.linger_warning():
            lines.append(warning)
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
        self._require_installed()
        if not self._backend.start():
            msg = (
                f"{self._SPEC.display_name} start failed. See "
                "~/.punt-labs/lux/logs/ for details."
            )
            raise ServiceActionFailedError(msg)
        return f"{self._SPEC.display_name} started."

    def restart(self) -> str:
        """Atomically restart via the supervisor -- no pid file, no signal-and-wait."""
        self._require_installed()
        if not self._backend.restart():
            msg = (
                f"{self._SPEC.display_name} restart failed. See "
                "~/.punt-labs/lux/logs/ for details."
            )
            raise ServiceActionFailedError(msg)
        return f"{self._SPEC.display_name} restarted."

    def _require_installed(self) -> None:
        """Raise :class:`ServiceNotInstalledError` unless the config exists."""
        if not self._backend.config_path().exists():
            msg = (
                f"{self._SPEC.display_name} is not installed. "
                f"Run 'lux {self._SPEC.cli_verb} install' first."
            )
            raise ServiceNotInstalledError(msg)

    @property
    def is_active(self) -> bool:
        """Return whether the service is currently running."""
        return self._backend.is_active()

    @property
    def spec(self) -> ServiceSpec:
        """Return the spec identifying this managed service."""
        return self._SPEC

    def doctor(self) -> DoctorResult:
        """Diagnose this service, read-only (``lux <verb> doctor``)."""
        return DoctorResult.diagnose(self._legacy_sweep, self._port_guard, self._SPEC)

    def doctor_fix(self) -> DoctorResult:
        """Repair this service, same objects :meth:`install` uses (``--fix``)."""
        return DoctorResult.repair(self._legacy_sweep, self._port_guard, self._SPEC)


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
