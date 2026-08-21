"""Daemon lifecycle for hub and display services via launchd/systemd."""

from __future__ import annotations

import logging
import os
import platform
from typing import ClassVar, Self, final

from punt_lux._backend_launchd import LaunchdBackend
from punt_lux._backend_systemd import SystemdBackend
from punt_lux._backends import ServiceBackend, has_linger
from punt_lux._doctor_result import DoctorResult
from punt_lux._legacy_sweep import LegacySweep
from punt_lux._legacy_sweep_launchd import LaunchdLegacySweep
from punt_lux._legacy_sweep_systemd import SystemdLegacySweep
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
        is_macos = detect_platform() == "macos"
        backend_cls = LaunchdBackend if is_macos else SystemdBackend
        sweep_cls = LaunchdLegacySweep if is_macos else SystemdLegacySweep
        self._backend = backend_cls(cls._SPEC)
        self._legacy_sweep = sweep_cls(cls._SPEC)
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
        """Install the service and return a status message.

        Cures any legacy launchd/systemd registration left by a prior
        rename, and refuses to proceed onto a port held by a foreign
        process, before writing this service's own config -- a rename is a
        migration, not a hope.
        """
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

    def restart(self) -> str:
        """Atomically restart the service via its supervisor.

        The supervisor already knows the daemon's pid, so a restart is one
        call — never a signal-and-wait against a pid file the daemon does
        not itself keep current. Refuses when the service is not installed
        so the caller gets the same "run install" hint as :meth:`start`.
        """
        if not self._backend.config_path().exists():
            msg = (
                f"{self._SPEC.display_name} is not installed. "
                f"Run 'lux {self._SPEC.cli_verb} install' first."
            )
            raise ServiceNotInstalledError(msg)
        if not self._backend.restart():
            msg = (
                f"{self._SPEC.display_name} restart failed. See "
                "~/.punt-labs/lux/logs/ for details."
            )
            raise ServiceActionFailedError(msg)
        return f"{self._SPEC.display_name} restarted."

    @property
    def is_active(self) -> bool:
        """Return whether the service is currently running."""
        return self._backend.is_active()

    @property
    def spec(self) -> ServiceSpec:
        """Return the spec identifying this managed service."""
        return self._SPEC

    def doctor(self, *, fix: bool) -> DoctorResult:
        """Diagnose (``fix=False``) or repair (``fix=True``) this service.

        ``lux <verb> doctor`` and ``install()`` invoke the same
        ``_legacy_sweep``/``_port_guard`` objects -- one implementation,
        two entries. Without ``fix``, only the non-mutating
        :meth:`~punt_lux._legacy_sweep.LegacySweep.diagnose` and
        :meth:`~punt_lux._port_guard.PortGuard.check` run. With ``fix``,
        :meth:`~punt_lux._legacy_sweep.LegacySweep.sweep` and
        :meth:`~punt_lux._port_guard.PortGuard.guard` run -- a failure of
        either is recorded as ``repair_failed``, never raised past this
        method, so the CLI can render the result and choose its own exit
        code.
        """
        if not fix:
            legacy = self._legacy_sweep.diagnose()
            port = self._port_guard.check()
            return DoctorResult(
                display_name=self._SPEC.display_name,
                process_name=self._SPEC.process_name,
                health_port=self._SPEC.health_port,
                legacy=legacy,
                port=port,
                repair_failed=False,
            )
        repair_failed = False
        try:
            legacy = self._legacy_sweep.sweep()
        except ServiceMigrationError:
            legacy = self._legacy_sweep.diagnose()
            repair_failed = True
        port = self._port_guard.check()
        if self._SPEC.health_port is not None and port.status not in ("free", "ours"):
            try:
                self._port_guard.guard()
                port = self._port_guard.check()
            except PortConflictError:
                repair_failed = True
        return DoctorResult(
            display_name=self._SPEC.display_name,
            process_name=self._SPEC.process_name,
            health_port=self._SPEC.health_port,
            legacy=legacy,
            port=port,
            repair_failed=repair_failed,
        )


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
