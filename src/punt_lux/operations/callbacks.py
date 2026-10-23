"""CallbackOperations — register menu callbacks.

A menu item is a session's callback. This concern owns the Hub-side move of the
callback model that is a write: a push-reachable, identified session *registers*
a callback (a menu write the replicator pushes). The *menu build*, which reads the
live sessions into the uniform ``Clients`` tree, is the read of
:class:`~punt_lux.domain.hub.callback_menu.CallbackMenuReplica`. Routing a click
to the owning session's live listener is the ``CallbackRouter``'s own move,
driven from the interaction dispatch, not from this facade; this concern only
*peeks* at what a router has buffered, through :meth:`pending_callbacks`.

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

from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.hub.session_callback import CallbackInvocation
from punt_lux.operations.models.common import OpError
from punt_lux.operations.models.menu_results import Ok

if TYPE_CHECKING:
    from punt_lux.domain.hub.callback_hold import CallbackRouter
    from punt_lux.domain.hub.client_lifecycle import ClientLifecycle
    from punt_lux.domain.hub.listener_legs import ListenerLegs
    from punt_lux.domain.hub.registry_outcomes import CallbackRegistration
    from punt_lux.operations.models.callbacks import RegisterCallbackRequest
    from punt_lux.operations.ports import DirtyMarker
    from punt_lux.operations.scope import Scope

__all__ = ["CallbackOperations"]

# What a caller that cannot be pushed to is told, naming both the requirement and
# the way to meet it. A session reaching the Hub over MCP or a one-shot REST call
# has no leg a click can arrive on; a session's applet holds one.
# One value: no leg at the gate, and a leg that went between the gate and the
# write, leave the caller in exactly the same position.
_PUSH_REQUIRED = OpError(
    code="push_required",
    reason="this connection holds no listen leg, so a click on the menu item could "
    "never reach it; register from a connection holding luxd's /ws leg — a "
    "session's applet, or a client built with LuxClient.listener",
)


@final
class CallbackOperations:
    """Register callbacks, route their clicks, and re-push the menu."""

    _lifecycle: ClientLifecycle
    _legs: ListenerLegs
    _router: CallbackRouter
    _replicator: DirtyMarker
    __slots__ = ("_legs", "_lifecycle", "_replicator", "_router")

    def __new__(
        cls,
        lifecycle: ClientLifecycle,
        legs: ListenerLegs,
        router: CallbackRouter,
        replicator: DirtyMarker,
    ) -> Self:
        self = super().__new__(cls)
        self._lifecycle = lifecycle
        self._legs = legs
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
        Committing anyway would leave a menu item with no listener to withdraw it.
        """
        if isinstance(request, OpError):
            return request
        self._lifecycle.renew(scope.connection_id, scope.client_host)
        expected = self._legs.listener_for(scope.connection_id)
        if expected is None:
            return _PUSH_REQUIRED
        return self._registered(
            self._legs.register_callback(
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

    def pending_callbacks(self, *, scope: Scope) -> tuple[CallbackInvocation, ...]:
        """Return the caller's held callback invocations without clearing them.

        Exposes :meth:`CallbackRouter.pending` at the facade so a client that
        wants to *observe* what has been buffered for its session -- without
        taking delivery of it -- can do so through the one code path every
        surface calls into. Delivery still goes through the listen leg's
        ``take`` drain; ``pending`` is a peek, not a poll.
        """
        return self._router.pending(scope.connection_id)

    def drop_session(self) -> None:
        """Re-push the menu after a session departs so its submenu vanishes.

        The departed session is removed from the live set by the disconnect
        cascade; the callback menu reads that set fresh at send time, so a single
        ``mark_menus`` here is enough to drop the session's submenu from the
        display — no per-session bookkeeping, the same read-at-send discipline the
        agent bar uses.
        """
        self._replicator.mark_menus()
