"""Best-effort teardown of a disconnected MCP session's Hub-side state.

When an MCP session ends, its Hub-side state must be released: the session's menu
items and the connection disconnect cascade (scenes, subscriptions, writer,
inbox). Each leg runs arbitrary handler code, so a raise in one must neither skip
the other nor escape unattributed to the SDK's session runner. This unit brackets
each leg and logs its failure against the session key; a programmer error
propagates only after every leg has run.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.hub import disconnect_connection
from punt_lux.domain.programmer_error import ProgrammerError
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
        """Drop the menu items, then always cascade the disconnect, then re-raise."""
        try:
            self._leg("menu", key, lambda: OPERATIONS.drop_session(self._connection_id))
        finally:
            self._leg(
                "disconnect", key, lambda: disconnect_connection(self._connection_id)
            )

    def _leg(self, leg: str, key: str, step: Callable[[], None]) -> None:
        """Run one leg, logging its failure; only a programmer error escapes."""
        try:
            step()
        except Exception as exc:
            logger.exception("MCP teardown failed: leg=%s session_key=%s", leg, key)
            if isinstance(exc, ProgrammerError):
                raise  # run() lets the other leg go first, then this propagates
