"""MenuArmingDeps — what arming a session touches, and the arming built from it."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Self

from punt_lux.operations.menu_arming import MenuArming
from punt_lux.operations.menus import MenuDepartureSink

if TYPE_CHECKING:
    from punt_lux.domain.hub.hub_display import HubDisplay
    from punt_lux.domain.hub.menu_registry import HubMenuRegistry
    from punt_lux.operations.ports import DirtyMarker, EnsureWriter

__all__ = ["MenuArmingDeps"]


@dataclass(frozen=True, slots=True)
class MenuArmingDeps:
    """The Hub store, whose lifecycle admits and arms, and the inbox-writer port."""

    display: HubDisplay
    ensure_writer: EnsureWriter

    @classmethod
    def over(
        cls,
        display: HubDisplay,
        registry: HubMenuRegistry,
        replicator: DirtyMarker,
        ensure_writer: EnsureWriter,
    ) -> Self:
        """Wire arming over the Hub store, seating the production menu sink on it."""
        display.lifecycle.present_as(
            replicator, MenuDepartureSink(registry, replicator)
        )
        return cls(display, ensure_writer)

    def arming(self) -> MenuArming:
        """The :class:`MenuArming` over these collaborators."""
        return MenuArming(self)
