"""MenuArmingDeps — what arming a session touches, and the arming built from it."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from punt_lux.operations.menu_arming import MenuArming

if TYPE_CHECKING:
    from punt_lux.domain.hub.hub_clients import HubClientRegistry
    from punt_lux.domain.ids import ConnectionId
    from punt_lux.operations.ports import EnsureWriter

__all__ = ["MenuArmingDeps"]


@dataclass(frozen=True, slots=True)
class MenuArmingDeps:
    """The registry, the inbox, the prune binding, and the menu push arming uses.

    ``arm_departure`` binds the session's menu-registry prune as a departure sink,
    so a lease-lapse departure (not only a graceful disconnect) withdraws its bar.
    """

    clients: HubClientRegistry
    ensure_writer: EnsureWriter
    arm_departure: Callable[[ConnectionId], None]
    mark_menus: Callable[[], None]

    def arming(self) -> MenuArming:
        """The :class:`MenuArming` over these collaborators."""
        return MenuArming(self)
