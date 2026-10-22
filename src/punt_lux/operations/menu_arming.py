"""MenuArming — the ``menu_set`` session precondition, distinct from the callback's.

Both menu families refuse an anonymous session, but keep their own precondition.
``register_callback`` needs a held listen leg (a callback must *launch* instantly);
``menu_set`` needs only that the session has identified and its inbox is armed.

This is the ``menu_set`` half: admit an identified session by arming its inbox
writer and departure sink. ``track`` binds the same departure prune for any
identified connection, so one that never sets a menu still withdraws its Clients
entry when it leaves.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from punt_lux.domain.hub.client_identity import ClientIdentity
    from punt_lux.domain.ids import ConnectionId
    from punt_lux.operations.menu_arming_deps import MenuArmingDeps

__all__ = ["MenuArming"]


@final
class MenuArming:
    """Admit an identified session to own a menu bar, arming its inbox and prune."""

    _deps: MenuArmingDeps
    __slots__ = ("_deps",)

    def __new__(cls, deps: MenuArmingDeps) -> Self:
        self = super().__new__(cls)
        self._deps = deps
        return self

    def admit(self, connection_id: ConnectionId) -> bool:
        """Renew the caller, arm its inbox and menu prune iff identified; report if in.

        An identified session has its lease renewed, its inbox writer armed, and
        its menu prune bound as a departure sink, so every departure trigger
        withdraws its bar (modelled in ``docs/menu_lifecycle.tex``). An anonymous
        session is refused, arming nothing.
        """
        deps = self._deps
        deps.clients.renew_if_registered(connection_id)
        if deps.clients.identity_of(connection_id) is None:
            return False
        deps.ensure_writer(connection_id)
        deps.arm_departure(connection_id)
        return True

    def track(self, connection_id: ConnectionId, before: ClientIdentity | None) -> None:
        """Bind the prune and re-push the Clients menu if the identity changed.

        ``before`` is what the connection declared until now. The same declaration
        repeated changes nothing, so it neither re-binds nor re-pushes. The caller
        holds the store's write lock, so a departure cannot land between the check
        and the bind.
        """
        deps = self._deps
        if deps.clients.identity_of(connection_id) not in (None, before):
            deps.arm_departure(connection_id)
            deps.mark_menus()
