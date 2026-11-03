"""MenuArmingDeps — what arming a session touches, and the arming built from it."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from punt_lux.operations.menu_arming import MenuArming

if TYPE_CHECKING:
    from punt_lux.domain.hub.client_lifecycle import ClientLifecycle
    from punt_lux.domain.hub.hub_clients import HubClientRegistry
    from punt_lux.operations.ports import EnsureWriter

__all__ = ["MenuArmingDeps"]


@dataclass(frozen=True, slots=True)
class MenuArmingDeps:
    """The door a session arms through, the roster it is read from, the inbox port."""

    lifecycle: ClientLifecycle
    clients: HubClientRegistry
    ensure_writer: EnsureWriter

    def arming(self) -> MenuArming:
        """The :class:`MenuArming` over these collaborators."""
        return MenuArming(self)
