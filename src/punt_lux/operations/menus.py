"""MenuOperations — the Hub-owned agent menu bar as one code path.

Menus are UI the agent submits, so the Hub owns them. ``set_menu`` admits the
caller through :class:`~punt_lux.operations.menu_arming.MenuArming` (identified,
inbox armed), records that session as the bar's owner — so two sessions never
clobber and a click routes back to the one that set it — and hands the whole
composed bar to the replicator, the same mark-and-replicate path a scene change
takes. ``list_menus`` reads the live bar with no reach-around, then appends the
Clients menu.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.operations.models.common import OpError
from punt_lux.operations.models.menu_results import MenuList, Ok

if TYPE_CHECKING:
    from punt_lux.domain.hub.menu_models import Menu
    from punt_lux.domain.hub.menu_registry import HubMenuRegistry
    from punt_lux.domain.ids import ConnectionId
    from punt_lux.operations.callbacks import CallbackMenuSource
    from punt_lux.operations.menu_arming import MenuArming
    from punt_lux.operations.models.menu_results import SetMenuRequest
    from punt_lux.operations.ports import DirtyMarker
    from punt_lux.operations.scope import Scope

__all__ = ["MenuOperations"]


@final
class MenuOperations:
    """Own the agent menu bar in the Hub; the replicator pushes every change."""

    _registry: HubMenuRegistry
    _replicator: DirtyMarker
    _callback_menus: CallbackMenuSource
    _arming: MenuArming
    __slots__ = ("_arming", "_callback_menus", "_registry", "_replicator")

    def __new__(
        cls,
        registry: HubMenuRegistry,
        replicator: DirtyMarker,
        callback_menus: CallbackMenuSource,
        arming: MenuArming,
    ) -> Self:
        self = super().__new__(cls)
        self._registry = registry
        self._replicator = replicator
        self._callback_menus = callback_menus
        self._arming = arming
        return self

    def set_menu(
        self, request: SetMenuRequest | OpError, *, scope: Scope
    ) -> Ok | OpError:
        """Record the caller's menu bar and push it, or return why not.

        Refuses an anonymous session (nothing anonymous owns a menu item); an
        admitted session's inbox is armed so a click has somewhere to land, and the
        bar is keyed under the caller so it neither clobbers nor is clobbered.
        """
        if isinstance(request, OpError):
            return request
        if not self._arming.admit(scope.connection_id):
            return OpError.identification_required(
                "declare an identity to own the menu items this session sets"
            )
        self._registry.set_menus(scope.connection_id, request.menus)
        self._push()
        return Ok()

    def list_menus(self) -> MenuList:
        """Return the live agent menu bar plus the ``Clients`` menu, no reach-around."""
        menus = list(self._registry.menu_bar())
        menus.extend(self._callback_menus.callback_menus())
        return MenuList(menus=menus)

    def get_menu(self, label: str) -> Menu | OpError:
        """Return the one menu named ``label``, or a ``not_found`` error."""
        matches = filter(lambda m: m.label == label, self.list_menus().menus)
        return next(matches, self._not_found(label))

    def drop_session(self, connection_id: ConnectionId) -> None:
        """Prune the departed session's bar; the caller re-pushes.

        Correctness does not hinge on this — the registry filters to the live set
        at send time — but it reclaims the entry so a departed owner's bar cannot
        linger even in memory.
        """
        self._registry.drop_session(connection_id)

    @staticmethod
    def _not_found(label: str) -> OpError:
        return OpError(code="not_found", reason=f"menu {label!r} not found")

    def _push(self) -> None:
        """Flag the change; the replicator reads the registry fresh at send time."""
        self._replicator.mark_menus()
