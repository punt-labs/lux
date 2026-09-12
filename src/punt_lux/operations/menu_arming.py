"""MenuArming — the ``menu_set`` session precondition, distinct from the callback's.

Both menu families refuse an anonymous session — nothing anonymous owns a menu
item — but they promise different things once admitted, so they keep their own
precondition. ``register_callback`` needs a held listen leg (a callback must
*launch* in the time a user reads as instant). ``menu_set`` needs only that the
session has identified and that its inbox is armed, because a ``menu_set`` click is
an agent-in-the-loop notification delivered on that inbox — not a sub-100 ms push.

This is the ``menu_set`` half: admit an identified session by arming its inbox
writer and departure sink, and refuse an anonymous one.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from punt_lux.domain.hub.hub_clients import HubClientRegistry
    from punt_lux.domain.ids import ConnectionId
    from punt_lux.operations.ports import EnsureWriter

__all__ = ["MenuArming"]


@final
class MenuArming:
    """Admit an identified session to own a menu bar, arming its inbox."""

    _clients: HubClientRegistry
    _ensure_writer: EnsureWriter
    __slots__ = ("_clients", "_ensure_writer")

    def __new__(cls, clients: HubClientRegistry, ensure_writer: EnsureWriter) -> Self:
        self = super().__new__(cls)
        self._clients = clients
        self._ensure_writer = ensure_writer
        return self

    def admit(self, connection_id: ConnectionId) -> bool:
        """Renew the caller, arm its inbox iff identified, and report whether admitted.

        An identified session has its lease renewed and its inbox writer and
        departure sink armed (so a click on its bar has somewhere to land and is
        released when it leaves); an anonymous one is refused, arming nothing.
        """
        self._clients.renew_if_registered(connection_id)
        if not self._identified(connection_id):
            return False
        self._ensure_writer(connection_id)
        return True

    def _identified(self, connection_id: ConnectionId) -> bool:
        """Whether the session has declared an identity — the ownership gate."""
        session = self._clients.session_of(connection_id)
        return session is not None and session.identity is not None
