"""MenuOperations — the Hub-owned agent menu bar as one code path.

Menus are UI the agent submits, so the Hub owns them. ``set_menu`` writes the Hub
menu registry and hands the whole composed bar to the replicator, which is the
sole writer to the display — the same mark-and-replicate path a scene change
takes, with no second writer. ``list_menus`` reads the registry with no
reach-around, then appends the session-then-callback submenus.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.operations.models.common import OpError
from punt_lux.operations.models.menu_results import MenuList, Ok

if TYPE_CHECKING:
    from punt_lux.domain.hub.menu_registry import HubMenuRegistry
    from punt_lux.operations.callbacks import CallbackMenuSource
    from punt_lux.operations.models.menu_results import SetMenuRequest
    from punt_lux.operations.ports import DirtyMarker

__all__ = ["MenuOperations"]


@final
class MenuOperations:
    """Own the agent menu bar in the Hub; the replicator pushes every change."""

    _registry: HubMenuRegistry
    _replicator: DirtyMarker
    _callback_menus: CallbackMenuSource
    __slots__ = ("_callback_menus", "_registry", "_replicator")

    def __new__(
        cls,
        registry: HubMenuRegistry,
        replicator: DirtyMarker,
        callback_menus: CallbackMenuSource,
    ) -> Self:
        self = super().__new__(cls)
        self._registry = registry
        self._replicator = replicator
        self._callback_menus = callback_menus
        return self

    def set_menu(self, request: SetMenuRequest | OpError) -> Ok | OpError:
        """Replace the agent-defined menu bar and push it, or pass the error on."""
        if isinstance(request, OpError):
            return request
        self._registry.set_menus(request.menus)
        self._push()
        return Ok()

    def list_menus(self) -> MenuList:
        """Return the whole Hub-authoritative menu state with no reach-around.

        Reports the agent menu bar, then the session-then-callback submenus for the
        live sessions. One read inventories every menu the Hub owns: the agent bar
        the agent set and the callback model built from the live sessions.
        """
        menus = list(self._registry.menu_bar())
        menus.extend(self._callback_menus.callback_menus())
        return MenuList(menus=menus)

    def _push(self) -> None:
        """Flag the menu change for the replicator — the sole display writer.

        The flag is payload-less: the worker reads the registry fresh at send
        time, so whatever the registry holds when the send runs is what the
        display receives — the scene-pattern that makes a stale push impossible.
        """
        self._replicator.mark_menus()
