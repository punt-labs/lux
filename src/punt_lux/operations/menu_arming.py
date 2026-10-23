"""MenuArming — the ``menu_set`` session precondition, distinct from the callback's.

Both menu families refuse an anonymous session — nothing anonymous owns a menu
item — but they promise different things once admitted, so they keep their own
precondition. ``register_callback`` needs a held listen leg (a callback must
*launch* in the time a user reads as instant). ``menu_set`` needs only that the
session has identified and that its inbox is armed, because a ``menu_set`` click is
an agent-in-the-loop notification delivered on that inbox — not a sub-100 ms push.

This is the ``menu_set`` half: admit an identified session by arming its inbox
writer and the Hub's one shared menu sink, and refuse an anonymous one.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from punt_lux.operations.menu_arming_deps import MenuArmingDeps
    from punt_lux.operations.scope import Scope

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

    def admit(self, scope: Scope) -> bool:
        """Renew the caller, arm its inbox and menu prune iff identified; report if in.

        An identified session has its lease renewed, its inbox writer armed (so a
        click has somewhere to land), and the Hub's shared menu sink bound — so
        EVERY departure trigger (graceful disconnect or the lease timer) withdraws
        its bar, not only the graceful leg (MO: menuOwner ⊆ registered, modelled in
        ``docs/menu_lifecycle.tex``). An anonymous session is refused, arming
        nothing.
        """
        deps = self._deps
        connection_id = scope.connection_id
        deps.lifecycle.renew(connection_id, scope.client_host)
        if deps.clients.identity_of(connection_id) is None:
            return False
        deps.ensure_writer(connection_id, scope.client_host)
        deps.lifecycle.arm(connection_id)
        return True
