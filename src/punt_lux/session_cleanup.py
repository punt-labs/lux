"""Best-effort teardown of a disconnected MCP session's Hub-side state.

When an MCP session ends — the client disconnects, or the SDK reaps it on idle
timeout — its Hub-side state must be released: the session's menu items and the
connection disconnect cascade (scenes, subscriptions, writer, inbox). Each leg
runs arbitrary Hub-side handler code, so a raise in one leg must neither skip
the remaining legs nor escape to the SDK's session runner, where it would
surface as an unattributed "session crashed" with no session key. This unit
brackets each leg and logs its failure against the session key, in luxd's log.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.hub import disconnect_connection
from punt_lux.domain.hub.inbox import drop_session
from punt_lux.operations import Scope
from punt_lux.tools.tools import OPERATIONS

if TYPE_CHECKING:
    from collections.abc import Callable

    from punt_lux.domain.ids import ConnectionId

logger = logging.getLogger(__name__)

__all__ = ["SessionCleanup"]


@final
class SessionCleanup:
    """Run a disconnected session's teardown legs in isolation."""

    _connection_id: ConnectionId
    __slots__ = ("_connection_id",)

    def __new__(cls, connection_id: ConnectionId) -> Self:
        self = super().__new__(cls)
        self._connection_id = connection_id
        return self

    def run(self, key: str) -> None:
        """Drop the session's menu items, then cascade the connection disconnect.

        Legs are independent and idempotent; each is isolated so one failing leg
        never starves the other.
        """
        self._leg(
            "menu", key, lambda: OPERATIONS.drop_session(Scope(self._connection_id))
        )
        self._leg(
            "disconnect",
            key,
            lambda: disconnect_connection(self._connection_id, drop_session),
        )

    def _leg(self, leg: str, key: str, step: Callable[[], None]) -> None:
        """Run one teardown leg, logging and swallowing its failure."""
        try:
            step()
        except Exception:
            logger.exception(
                "MCP session teardown failed: leg=%s session_key=%s", leg, key
            )
