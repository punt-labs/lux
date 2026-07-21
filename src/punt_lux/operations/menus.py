"""MenuOperations — the Hub-owned menu bar as one code path.

Menus are UI the agent submits, so the Hub owns them. ``set_menu`` and
``register_menu_item`` write the Hub menu registry and hand the whole composed
bar to the replicator, which is the sole writer to the display — the same
mark-and-replicate path a scene change takes, with no second writer.
``list_menus`` reads the registry with no reach-around.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, cast, final

from punt_lux.client_label import ClientLabel
from punt_lux.domain.hub.menu_models import Menu
from punt_lux.operations.models.common import OpError
from punt_lux.operations.models.menu_results import MenuList, Ok

if TYPE_CHECKING:
    from punt_lux.domain.hub.menu_models import MenuAction, MenuEntry
    from punt_lux.domain.hub.menu_registry import HubMenuRegistry
    from punt_lux.operations.models.menu_results import SetMenuRequest
    from punt_lux.operations.ports import DirtyMarker
    from punt_lux.operations.scope import Scope

__all__ = ["MenuOperations"]

# The display groups every registered item under Applications → the registering
# client's submenu. luxd is the one display connection, so all items render under
# its label; list_menus reports that same structure so the read matches the screen.
_APPLICATIONS_LABEL = "Applications"
_LUX_SUBMENU_LABEL = ClientLabel.of(ClientLabel.LUX)


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
        self._registry.set_menus(request.menus)
        self._push()
        return Ok()

    def register_menu_item(self, action: MenuAction, *, scope: Scope) -> Ok:
        """Register a tool item for the caller's session and push the menu state."""
        self._registry.register_item(scope.connection_id, action)
        self._push()
        return Ok()

    def drop_session(self, scope: Scope) -> None:
        """Forget a departed session's tool items and re-push the menu state.

        Dropping alone would leave the display's World menu stale until the next
        unrelated menu write; the push here removes the departed items at once,
        riding the same mark-and-replicate path every menu write takes.
        """
        self._registry.drop(scope.connection_id)
        self._push()

    def list_menus(self) -> MenuList:
        """Return the whole Hub-authoritative menu state with no reach-around.

        Reports the agent menu bar plus, when any tool items are registered, the
        Applications menu composed exactly as the display renders it: a per-client
        submenu (luxd's label) holding the items sorted by label. One read
        inventories everything the Hub owns, matching what is on screen.
        """
        menus = list(self._registry.menu_bar())
        items = self._registry.registered_items()
        if items:
            menus.append(self._applications_menu(items))
        return MenuList(menus=menus)

    @staticmethod
    def _applications_menu(items: list[MenuAction]) -> Menu:
        """Compose the Applications menu the display renders for the tool items.

        The display groups items by their registering socket client under
        Applications and sorts each submenu's items by label; luxd is that one
        client, so its submenu gathers them all.
        """
        ordered = cast(
            "list[MenuEntry]", sorted(items, key=lambda action: action.label)
        )
        submenu: list[MenuEntry] = [Menu(label=_LUX_SUBMENU_LABEL, items=ordered)]
        return Menu(label=_APPLICATIONS_LABEL, items=submenu)

    def _push(self) -> None:
        """Flag the menu change for the replicator — the sole display writer.

        The flag is payload-less: the worker reads the registry fresh at send
        time, so whatever the registry holds when the send runs is what the
        display receives — the scene-pattern that makes a stale push impossible.
        """
        self._replicator.mark_menus()
