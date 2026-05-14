"""Daemon lifecycle management for luxd.

Provides ``ServiceManager`` to register luxd as a system service
(launchd on macOS, systemd on Linux) so the daemon starts at login
and restarts on crash.
"""

from __future__ import annotations

import logging
import os
import platform
from pathlib import Path
from typing import Self

from punt_lux._backends import (
    LaunchdBackend,
    ServiceBackend,
    SystemdBackend,
    has_linger,
)
from punt_lux.hub import DEFAULT_HUB_PORT

logger = logging.getLogger(__name__)


def detect_platform() -> str:
    """Return ``'macos'`` or ``'linux'``. Raise on unsupported platforms."""
    system = platform.system()
    if system == "Darwin":
        return "macos"
    if system == "Linux":
        return "linux"
    msg = f"Unsupported platform: {system}. lux hub-install supports macOS and Linux."
    raise SystemExit(msg)


class ServiceManager:
    """Coordinate daemon lifecycle across platforms."""

    __slots__ = ("_backend",)

    _backend: ServiceBackend

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._backend = cls._resolve_backend()
        return self

    @staticmethod
    def _resolve_backend() -> ServiceBackend:
        """Return the backend matching the current platform."""
        plat = detect_platform()
        if plat == "macos":
            return LaunchdBackend()
        return SystemdBackend()

    @staticmethod
    def _luxd_exec_args() -> list[str]:
        """Return the command to invoke luxd.

        Resolution order:

        1. ``~/.local/bin/luxd`` (uv tool install symlink).
        2. Refuse to register -- raise ``RuntimeError`` instead of
           silently using ``sys.executable`` or ``shutil.which()``,
           either of which may resolve to a dev venv binary.
        """
        local_bin = Path.home() / ".local" / "bin" / "luxd"
        if local_bin.exists():
            # Symlink path, not resolve() -- stable across uv tool upgrade.
            logger.info("Service binary: %s (uv tool)", local_bin)
            return [str(local_bin), "--port", str(DEFAULT_HUB_PORT)]

        msg = (
            "Cannot find luxd binary at ~/.local/bin/luxd. "
            "Install lux first: uv tool install punt-lux"
        )
        raise RuntimeError(msg)

    def install(self) -> str:
        """Install luxd as a system service. Return a status message."""
        exec_args = self._luxd_exec_args()
        self._backend.install(exec_args)
        is_running = self._backend.is_active()

        exec_display = " ".join(exec_args)
        status_label = "running" if is_running else "installed (not yet running)"
        lines = [
            f"luxd {status_label} on port {DEFAULT_HUB_PORT}.",
            f"  Service: {self._backend.config_path()}",
            f"  Command: {exec_display}",
        ]
        if isinstance(self._backend, SystemdBackend) and not has_linger():
            lines.append(
                "  Warning: loginctl linger is not enabled. "
                "The daemon will stop when you log out. "
                "Run: loginctl enable-linger"
            )
        return os.linesep.join(lines)

    def uninstall(self) -> str:
        """Remove luxd system service. Return a status message."""
        path = self._backend.config_path()
        self._backend.uninstall()
        return f"luxd uninstalled. Removed {path}."

    def restart(self) -> str:
        """Restart the daemon via uninstall + install cycle."""
        self._backend.uninstall()
        return self.install()

    @property
    def is_active(self) -> bool:
        """Return whether the daemon is currently running."""
        return self._backend.is_active()
