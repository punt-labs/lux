"""MenuOperations — the Hub-owned agent menu bar as one code path.

Menus are UI the agent submits, so the Hub owns them. ``set_menu`` admits the
caller through :class:`~punt_lux.operations.menu_arming.MenuArming`, records that
session as the bar's owner, and marks the bar for the replicator, the same path a
scene change takes. ``list_menus`` reads the live bar, then appends the Clients
menu.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Self, final

from punt_lux.operations.models.common import OpError
from punt_lux.operations.models.menu_results import MenuList, Ok

if TYPE_CHECKING:
    from collections.abc import Callable
    from contextlib import AbstractContextManager

    from punt_lux.domain.hub.client_identity import ClientIdentity
    from punt_lux.domain.hub.menu_models import Menu
    from punt_lux.domain.hub.menu_registry import HubMenuRegistry
    from punt_lux.domain.ids import ConnectionId
    from punt_lux.operations.callbacks import CallbackMenuSource
    from punt_lux.operations.menu_arming import MenuArming
    from punt_lux.operations.models.menu_results import SetMenuRequest
    from punt_lux.operations.ports import DirtyMarker
    from punt_lux.operations.scope import Scope

__all__ = ["MenuDepartureSink", "MenuOperations", "MenuOperationsDeps"]

# The Hub store's reentrant write lock, entered as a context manager. ``set_menu``
# holds it across the admit-liveness check AND the registry store so a departure
# cannot interleave between the gate and the write.
type WriteLock = Callable[[], AbstractContextManager[bool]]


@final
class MenuDepartureSink:
    """Withdraw a departed session's agent bar and re-push it, as a departure sink.

    Fired by the departure cascade on every trigger, graceful or lease-lapse.
    Without the mark the Display keeps the departed owner's entries until some
    later push. It runs inside the cascade's ``StoreLock``, so it only marks
    dirty -- a non-blocking signal -- and never sends under the lock.
    """

    _registry: HubMenuRegistry
    _replicator: DirtyMarker
    __slots__ = ("_registry", "_replicator")

    def __new__(cls, registry: HubMenuRegistry, replicator: DirtyMarker) -> Self:
        self = super().__new__(cls)
        self._registry = registry
        self._replicator = replicator
        return self

    def __call__(self, connection_id: ConnectionId) -> None:
        """Prune the departed owner's bar, then mark the menu bar for re-push."""
        self._registry.drop_session(connection_id)
        self._replicator.mark_menus()


@final
@dataclass(frozen=True, slots=True)
class MenuOperationsDeps:
    """The collaborators :class:`MenuOperations` owns the agent menu bar through."""

    registry: HubMenuRegistry
    replicator: DirtyMarker
    callback_menus: CallbackMenuSource
    arming: MenuArming
    write_lock: WriteLock


@final
class MenuOperations:
    """Own the agent menu bar in the Hub; the replicator pushes every change."""

    _registry: HubMenuRegistry
    _replicator: DirtyMarker
    _callback_menus: CallbackMenuSource
    _arming: MenuArming
    _write_lock: WriteLock
    __slots__ = (
        "_arming",
        "_callback_menus",
        "_registry",
        "_replicator",
        "_write_lock",
    )

    def __new__(cls, deps: MenuOperationsDeps) -> Self:
        self = super().__new__(cls)
        self._registry = deps.registry
        self._replicator = deps.replicator
        self._callback_menus = deps.callback_menus
        self._arming = deps.arming
        self._write_lock = deps.write_lock
        return self

    def set_menu(
        self, request: SetMenuRequest | OpError, *, scope: Scope
    ) -> Ok | OpError:
        """Record the caller's menu bar and push it, or return why not.

        Refuses an anonymous session. The admit check and the registry store run
        under one hold of the store's write lock, so a departure cannot land
        between them and leave an orphaned bar; the push is flagged after.
        """
        if isinstance(request, OpError):
            return request
        with self._write_lock():
            if not self._arming.admit(scope.connection_id):
                return self._anonymous()
            self._registry.set_menus(scope.connection_id, request.menus)
        self._replicator.mark_menus()
        return Ok()

    def identified(
        self, connection_id: ConnectionId, before: ClientIdentity | None
    ) -> None:
        """Re-push the Clients menu if the declaration changed who it lists."""
        with self._write_lock():
            self._arming.track(connection_id, before)

    def list_menus(self) -> MenuList:
        """Return the live agent menu bar plus the ``Clients`` menu."""
        menus = [*self._registry.menu_bar(), *self._callback_menus.callback_menus()]
        return MenuList(menus=menus)

    def get_menu(self, label: str) -> Menu | OpError:
        """Return the menu named ``label``, or ``not_found``."""
        matches = filter(lambda m: m.label == label, self.list_menus().menus)
        return next(matches, self._not_found(label))

    def drop_session(self, connection_id: ConnectionId) -> None:
        """Prune the departed session's bar; the caller re-pushes.

        The registry filters to the live set at send time, so this only reclaims
        the entry.
        """
        self._registry.drop_session(connection_id)

    @staticmethod
    def _anonymous() -> OpError:
        return OpError.identification_required(MenuOperations._anonymous_reason())

    @staticmethod
    def _anonymous_reason() -> str:
        return "declare an identity to own the menu items this session sets"

    @staticmethod
    def _not_found(label: str) -> OpError:
        return OpError(code="not_found", reason=f"menu {label!r} not found")
