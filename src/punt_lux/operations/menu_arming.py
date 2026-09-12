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

from collections.abc import Callable
from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from punt_lux.domain.hub.hub_clients import HubClientRegistry
    from punt_lux.domain.ids import ConnectionId
    from punt_lux.operations.ports import EnsureWriter

__all__ = ["MenuArming"]

# Bind the owning session's menu-registry prune as a departure sink, so a
# lease-lapse departure (not only a graceful disconnect) withdraws its bar.
type ArmDeparture = Callable[[ConnectionId], None]


@final
class MenuArming:
    """Admit an identified session to own a menu bar, arming its inbox and prune."""

    _clients: HubClientRegistry
    _ensure_writer: EnsureWriter
    _arm_departure: ArmDeparture
    __slots__ = ("_arm_departure", "_clients", "_ensure_writer")

    def __new__(
        cls,
        clients: HubClientRegistry,
        ensure_writer: EnsureWriter,
        arm_departure: ArmDeparture,
    ) -> Self:
        self = super().__new__(cls)
        self._clients = clients
        self._ensure_writer = ensure_writer
        self._arm_departure = arm_departure
        return self

    def admit(self, connection_id: ConnectionId) -> bool:
        """Renew the caller, arm its inbox and menu prune iff identified; report if in.

        An identified session has its lease renewed, its inbox writer armed (so a
        click has somewhere to land), and its menu-registry prune bound as a
        departure sink — so EVERY departure trigger (graceful disconnect or the
        lease timer) withdraws its bar, not only the graceful leg (MO: menuOwner ⊆
        registered, modelled in ``docs/menu_lifecycle.tex``). An anonymous session
        is refused, arming nothing.
        """
        self._clients.renew_if_registered(connection_id)
        if not self._identified(connection_id):
            return False
        self._ensure_writer(connection_id)
        self._arm_departure(connection_id)
        return True

    def _identified(self, connection_id: ConnectionId) -> bool:
        """Whether the session has declared an identity — the ownership gate."""
        session = self._clients.session_of(connection_id)
        return session is not None and session.identity is not None
