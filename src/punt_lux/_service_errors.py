"""Exceptions raised by :class:`ServiceManager` on install/start/stop failures."""

from __future__ import annotations

__all__ = [
    "PortConflictError",
    "ServiceActionFailedError",
    "ServiceMigrationError",
    "ServiceNotInstalledError",
]


class ServiceNotInstalledError(RuntimeError):
    """The service has not been installed; the message names the fix."""


class ServiceActionFailedError(RuntimeError):
    """The supervisor rejected a stop/start call; the message names the log."""


class ServiceMigrationError(RuntimeError):
    """A legacy launchd label or systemd unit could not be fully cleaned up.

    Carries the full :class:`~punt_lux._legacy_sweep.LegacySweepReport`
    text -- every failing identifier's repair line, not just the first.
    """


class PortConflictError(RuntimeError):
    """The service's port is held by an unverified or foreign process."""
