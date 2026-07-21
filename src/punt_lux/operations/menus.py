"""MenuOperations — the Hub-owned menu bar as one code path.

Menus are UI the agent submits, so the Hub owns them. ``set_menu`` and
``register_menu_item`` write the Hub menu registry and hand the whole composed
bar to the replicator, which is the sole writer to the display — the same
mark-and-replicate path a scene change takes, with no second writer.
``list_menus`` reads the registry with no reach-around.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.operations.models.common import OpError
from punt_lux.operations.models.menu_results import MenuList, Ok
from punt_lux.operations.models.menus import Menu

if TYPE_CHECKING:
    from punt_lux.domain.hub.menu_registry import HubMenuRegistry
    from punt_lux.operations.models.menu_results import SetMenuRequest
    from punt_lux.operations.models.menus import MenuAction
    from punt_lux.operations.ports import DirtyMarker
    from punt_lux.operations.scope import Scope

__all__ = ["MenuOperations"]


@final
class MenuOperations:
    """Own the menu bar in the Hub; the replicator pushes every change."""

    _registry: HubMenuRegistry
    _replicator: DirtyMarker
    __slots__ = ("_registry", "_replicator")

    def __new__(cls, registry: HubMenuRegistry, replicator: DirtyMarker) -> Self:
        self = super().__new__(cls)
        self._registry = registry
        self._replicator = replicator
        return self

    def set_menu(self, request: SetMenuRequest | OpError) -> Ok | OpError:
        """Replace the agent-defined menu bar and push it, or pass the error on."""
        if isinstance(request, OpError):
            return request
        self._registry.set_menus([menu.to_wire() for menu in request.menus])
        self._push()
        return Ok()

    def register_menu_item(self, action: MenuAction, *, scope: Scope) -> Ok:
        """Register a tool item for the caller's session and push the menu state."""
        self._registry.register_item(scope.connection_id, action.to_wire())
        self._push()
        return Ok()

    def list_menus(self) -> MenuList:
        """Return the whole Hub-authoritative menu state with no reach-around.

        Reports the agent menu bar plus, when any tool items are registered, a
        synthesized ``Tools`` menu gathering them — the same items the display
        shows in its World menu — so one read inventories everything the Hub owns.
        """
        menus = [Menu.from_wire(menu) for menu in self._registry.menu_bar()]
        items = self._registry.registered_items()
        if items:
            menus.append(Menu.from_wire({"label": "Tools", "items": items}))
        return MenuList(menus=menus)

    def _push(self) -> None:
        """Hand the whole menu state to the replicator — the sole display writer."""
        self._replicator.mark_menus(
            self._registry.menu_bar(), self._registry.registered_items()
        )
