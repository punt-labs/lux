"""Exceptions raised by :class:`ServiceManager` on install/start/stop failures."""

from __future__ import annotations

__all__ = ["ServiceActionFailedError", "ServiceNotInstalledError"]


class ServiceNotInstalledError(RuntimeError):
    """The service has not been installed; the message names the fix."""


class ServiceActionFailedError(RuntimeError):
    """The supervisor rejected a stop/start call; the message names the log."""
