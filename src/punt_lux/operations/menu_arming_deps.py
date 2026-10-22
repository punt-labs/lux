"""MenuArmingDeps — what arming a session touches, and the arming built from it."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Self

from punt_lux.operations.menu_arming import MenuArming
from punt_lux.operations.menus import MenuDepartureSink

if TYPE_CHECKING:
    from punt_lux.domain.hub.hub_clients import HubClientRegistry
    from punt_lux.domain.hub.hub_display import HubDisplay
    from punt_lux.domain.hub.menu_registry import HubMenuRegistry
    from punt_lux.domain.ids import ConnectionId
    from punt_lux.operations.ports import DirtyMarker, EnsureWriter

__all__ = ["MenuArmingDeps"]


@dataclass(frozen=True, slots=True)
class MenuArmingDeps:
    """The registry, inbox, prune binding, menu push and store lock arming uses.

    ``arm_departure`` binds the session's menu-registry prune as a departure sink,
    so a lease-lapse departure (not only a graceful disconnect) withdraws its bar.
    """

    clients: HubClientRegistry
    ensure_writer: EnsureWriter
    arm_departure: Callable[[ConnectionId], None]
    mark_menus: Callable[[], None]
    write_lock: Callable[[], AbstractContextManager[bool]]

    @classmethod
    def over(
        cls,
        display: HubDisplay,
        registry: HubMenuRegistry,
        replicator: DirtyMarker,
        ensure_writer: EnsureWriter,
    ) -> Self:
        """Wire arming over the Hub store, binding the production departure sink."""
        sink = MenuDepartureSink(registry, replicator)
        return cls(
            display.clients,
            ensure_writer,
            lambda c: display.bind_departure_sink(c, sink),
            replicator.mark_menus,
            display.write_lock,
        )

    def arming(self) -> MenuArming:
        """The :class:`MenuArming` over these collaborators."""
        return MenuArming(self)
