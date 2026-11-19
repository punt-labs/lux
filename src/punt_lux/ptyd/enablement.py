"""Coordinate terminal login registration without disrupting active sessions."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

from punt_lux.service import ServiceActionFailedError

if TYPE_CHECKING:
    from punt_lux._backends import ServiceBackend
    from punt_lux.service import ServiceManager


class TerminalEnablement:
    _manager: ServiceManager
    _backend: ServiceBackend
    __slots__ = ("_backend", "_manager")

    def __new__(cls, manager: ServiceManager, backend: ServiceBackend) -> Self:
        self = super().__new__(cls)
        self._manager = manager
        self._backend = backend
        return self

    def enable(self) -> str:
        """Preserve live programs while ensuring the owner starts at login."""
        if self._manager.is_active:
            if not self._backend.enable_autostart():
                raise ServiceActionFailedError("Could not enable luxd-pty at login.")
            return "luxd-pty enabled; running owner left unchanged."
        installed = self._manager.install()
        return (
            installed
            if self._manager.is_active
            else installed + "\n" + self._manager.start()
        )
