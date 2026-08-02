"""CallbackOperations — register menu callbacks, route their clicks, read the menu.

A menu item is a session's callback. This concern owns the three Hub-side moves of
the callback model: a push-reachable, identified session *registers* a callback (a
menu write the replicator pushes); a click *invokes* a callback, which the router
routes to the owning session's live listener; and the *menu build* reads the live
sessions into the uniform ``Clients`` tree.

Registration has two preconditions and refuses rather than half-granting either.
The connection must hold a listen leg, because a menu item that cannot be
delivered by push cannot launch at the speed a menu implies. And the session must
have identified, so nothing anonymous owns a menu item. Both are the session
registry's to answer — the leg, the identity, and the lease all live on the
session — so this concern keeps no duplicate of any of them, and the leg it reads
to decide the first goes back to the registry as the condition the write commits
under.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, Self, final, runtime_checkable

from punt_lux.domain.hub.callback_menu import CallbackMenu
from punt_lux.domain.hub.session_callback import CallbackInvocation
from punt_lux.operations.models.common import OpError
from punt_lux.operations.models.menu_results import Ok

if TYPE_CHECKING:
    from punt_lux.domain.hub.callback_hold import CallbackRouter, CallbackRouting
    from punt_lux.domain.hub.hub_clients import HubClientRegistry
    from punt_lux.domain.hub.menu_models import Menu
    from punt_lux.domain.hub.registry_outcomes import CallbackRegistration
    from punt_lux.operations.models.callbacks import RegisterCallbackRequest
    from punt_lux.operations.ports import DirtyMarker
    from punt_lux.operations.scope import Scope

__all__ = ["CallbackMenuSource", "CallbackOperations"]

# What a caller that cannot be pushed to is told, naming both the requirement and
# the way to meet it. A session reaching the Hub over MCP or a one-shot REST call
# has no leg a click can arrive on; a session's applet holds one.
# One value: no leg at the gate, and a leg that went between the gate and the
# write, leave the caller in exactly the same position.
_PUSH_REQUIRED = OpError(
    code="push_required",
    reason="this connection holds no listen leg, so a click on the menu item could "
    "never reach it; register from a connection holding luxd's /ws leg — a "
    "session's applet, or a client built with LuxRestClient.listener",
)


@runtime_checkable
class CallbackMenuSource(Protocol):
    """The read the menu surface composes into its bar — the Clients menu."""

    def callback_menus(self) -> list[Menu]:
        """Return the uniform ``Clients`` menu built from the live sessions."""
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

        Two preconditions, in the order that tells the caller the most. First the
        connection must be push-reachable — a menu item must launch in the time a
        user reads as instant, which only a held listen connection can promise —
        because no identity fixes a caller that could never be told its item was
        clicked. Then the session must have identified, refused with the same
        challenge a scene write returns, so nothing anonymous owns a menu item.
        A registration that took changes the menu, so the replicator re-pushes it.

        The leg read here is carried into the write, which commits only if that
        same leg still holds the connection. Reading and writing are separate
        moments — this runs on an MCP or REST thread, and the leg lives on the
        loop — so between them it may tear down or be replaced by a reconnect.
        Committing anyway would leave a menu item with no listener and nothing
        that would ever withdraw it, which is precisely what the gate is for.
        """
        if isinstance(request, OpError):
            return request
        expected = self._clients.listener_of(scope.connection_id)
        if expected is None:
            return _PUSH_REQUIRED
        return self._registered(
            self._clients.register_callback(
                scope.connection_id, request.callback, expected
            )
        )

    def _registered(self, outcome: CallbackRegistration) -> Ok | OpError:
        """Turn a registration outcome into its result, pushing the menu if it took."""
        if outcome == "superseded":
            return _PUSH_REQUIRED
        if outcome == "declined":
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

    def callback_menus(self) -> list[Menu]:
        """Build the uniform ``Clients`` menu from one read of the named clients."""
        return CallbackMenu.from_named(self._clients.named_sessions())

    def drop_session(self) -> None:
        """Re-push the menu after a session departs so its submenu vanishes.

        The departed session is removed from the live set by the disconnect
        cascade; the callback menu reads that set fresh at send time, so a single
        ``mark_menus`` here is enough to drop the session's submenu from the
        display — no per-session bookkeeping, the same read-at-send discipline the
        agent bar uses.
        """
        self._replicator.mark_menus()

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
