"""The platform-agnostic daemon lifecycle strategy for luxd.

Concrete backends live in their own modules --
:class:`~punt_lux.LaunchdBackend` in ``_backend_launchd.py``,
:class:`~punt_lux.SystemdBackend` in ``_backend_systemd.py`` -- so each
platform's plist/unit-file generation and process-management logic stays
under the 300-line module target.
"""

from __future__ import annotations

import os
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path

__all__ = ["ServiceBackend", "has_linger", "pgrep_pid"]


def pgrep_pid(process_name: str) -> int | None:
    """Return the pid of the running process, or ``None`` if none is up.

    ``pgrep -x`` matches the ``setproctitle`` name — the same string that
    shows in ``ps`` and Activity Monitor. Answers on both macOS and Linux
    without depending on a socket peer credential (the Hub speaks TCP and
    cannot expose one) or a pid file (the daemon may not yet have written
    it). Absence is the documented contract when nothing is up.
    """
    result = subprocess.run(
        ["pgrep", "-x", process_name],
        capture_output=True,
        text=True,
        check=False,
    )
    lines = result.stdout.strip().splitlines()
    if not lines:
        return None
    try:
        return int(lines[0])
    except ValueError:
        return None


class ServiceBackend(ABC):
    """Platform-specific daemon lifecycle strategy."""

    @abstractmethod
    def install(self) -> None:
        """Register and start the daemon service using its ``ServiceSpec``."""

    @abstractmethod
    def uninstall(self) -> None:
        """Stop and remove the daemon service."""

    @abstractmethod
    def stop(self) -> bool:
        """Stop the daemon without removing its service registration.

        Return whether the supervisor call succeeded -- the caller must not
        report success on a non-zero exit.
        """

    @abstractmethod
    def start(self) -> bool:
        """Start an already-installed, stopped daemon. Symmetric to :meth:`stop`.

        Return whether the supervisor call succeeded -- the caller must not
        report success on a non-zero exit.
        """

    @abstractmethod
    def restart(self) -> bool:
        """Atomically kill-and-respawn the daemon under its supervisor.

        The whole point of routing through the supervisor is that it already
        knows the daemon's pid — so a restart never has to read one from a
        file that the daemon does not itself keep current. Return whether the
        supervisor call succeeded; the caller must not report success on a
        non-zero exit.
        """

    @abstractmethod
    def is_active(self) -> bool:
        """Return whether the daemon is currently running."""

    @abstractmethod
    def config_path(self) -> Path:
        """Return the path to the service config file."""

    def linger_warning(self) -> str:
        """Return a post-install warning line, or ``""`` when none applies.

        Base case: no warning. Overridden by :class:`SystemdBackend`, whose
        supervisor stops the service at logout unless linger is enabled --
        a platform-specific concern this dispatches on the object, not an
        ``isinstance`` check at the call site.
        """
        return ""


def has_linger() -> bool:
    """Check if loginctl linger is enabled for the current user."""
    try:
        user = os.getlogin()
    except OSError:
        return True  # Can't check; don't warn
    try:
        result = subprocess.run(
            ["loginctl", "show-user", user, "--property=Linger"],
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return True  # No loginctl (container/minimal install); don't warn
    return "Linger=yes" in result.stdout
