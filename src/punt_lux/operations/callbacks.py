"""CallbackOperations — register menu callbacks, route their clicks, read the menu.

A menu item is a session's callback. This concern owns the three Hub-side moves of
the callback model: an identified session *registers* a callback (a menu write the
replicator pushes); a click *invokes* a callback, which the router holds for the
owning session until the delivery legs drain it; and the *menu build* reads the
live sessions into the uniform session-then-callback tree.

Identity and lease are the session registry's, read through it — this concern
keeps no duplicate. Registration is refused for a session that has not identified,
the same challenge a scene write returns, so nothing anonymous owns a menu item.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, Self, final, runtime_checkable

from punt_lux.domain.hub.callback_menu import CallbackMenu
from punt_lux.domain.hub.session_callback import CallbackInvocation
from punt_lux.operations.models.callbacks import PendingCallbacks
from punt_lux.operations.models.common import OpError
from punt_lux.operations.models.menu_results import Ok

if TYPE_CHECKING:
    from punt_lux.domain.hub.callback_hold import CallbackRouter, CallbackRouting
    from punt_lux.domain.hub.hub_clients import HubClientRegistry
    from punt_lux.domain.hub.menu_models import Menu
    from punt_lux.domain.ids import ConnectionId
    from punt_lux.operations.models.callbacks import RegisterCallbackRequest
    from punt_lux.operations.ports import DirtyMarker
    from punt_lux.operations.scope import Scope

__all__ = ["CallbackMenuSource", "CallbackOperations"]


@runtime_checkable
class CallbackMenuSource(Protocol):
    """The read the menu surface composes into its bar — the callback submenus."""

    def callback_menus(self) -> list[Menu]:
        """Return the uniform session-then-callback submenus for the live sessions."""
        ...


@final
class CallbackOperations:
    """Register callbacks, route their clicks, and read the callback menu."""

    _clients: HubClientRegistry
    _router: CallbackRouter
    _replicator: DirtyMarker
    __slots__ = ("_clients", "_replicator", "_router")

    def __new__(
        cls,
        clients: HubClientRegistry,
        router: CallbackRouter,
        replicator: DirtyMarker,
    ) -> Self:
        self = super().__new__(cls)
        self._clients = clients
        self._router = router
        self._replicator = replicator
        return self

    def register_callback(
        self, request: RegisterCallbackRequest | OpError, *, scope: Scope
    ) -> Ok | OpError:
        """Register the caller's callback and push the menu, or return why not.

        The session decides whether it accepts the callback: an unidentified or
        lapsed caller is refused with the identify challenge a scene write returns,
        never a silently orphaned menu item. A registration that took changes the
        menu, so the replicator re-pushes it.
        """
        if isinstance(request, OpError):
            return request
        if not self._clients.register_callback(scope.connection_id, request.callback):
            return OpError.identification_required(
                "declare an identity to own the menu callbacks this session registers"
            )
        self._replicator.mark_menus()
        return Ok()

    def invoke_callback(self, menu_id: str) -> Ok | OpError:
        """Route a clicked leaf's invocation to its owning session, or say why not.

        ``menu_id`` is the leaf id a click carries — the owning session and callback
        joined. A malformed id is an ``invalid_request``; a click for a departed
        session or an unregistered callback is ``not_found`` naming which.
        """
        try:
            invocation = CallbackInvocation.from_menu_id(menu_id)
        except ValueError as exc:
            return OpError(code="invalid_request", reason=str(exc))
        return self._result_for(self._router.route(invocation))

    def pending_callbacks(self, connection_id: ConnectionId) -> PendingCallbacks:
        """Return the callback ids held for a session, awaiting delivery to it."""
        held = self._router.pending(connection_id)
        return PendingCallbacks(callback_ids=tuple(inv.callback_id for inv in held))

    def callback_menus(self) -> list[Menu]:
        """Build the uniform session-then-callback submenus from the live sessions."""
        return CallbackMenu.from_sessions(self._clients.live_sessions())

    @staticmethod
    def _result_for(routing: CallbackRouting) -> Ok | OpError:
        """Map a routing outcome to the operation result the surfaces return."""
        if routing == "routed":
            return Ok()
        if routing == "provider_gone":
            return OpError(
                code="not_found",
                reason="the session that owns this menu item is gone",
            )
        return OpError(code="not_found", reason="this session has no such callback")
