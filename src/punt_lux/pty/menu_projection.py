"""The "New terminal" menu entry: register it, and start a shell per click."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, ClassVar, Self

from punt_lux.pty.daemon_exchange import DaemonExchange, SessionRefusedError
from punt_lux.wire.operations import OpError
from punt_lux.wire.stream.new_request import NewRequest

if TYPE_CHECKING:
    from punt_lux.pty.menu_clients import TerminalClients

logger = logging.getLogger(__name__)


class TerminalProjection:
    """The one menu entry; its callback id ties registration to its clicks.

    The window of each new shell is the keeper's to show, not this entry's.
    """

    _ENTRY_ID: ClassVar[str] = "terminal"
    _clients: TerminalClients
    _daemon: DaemonExchange
    _callback: str

    def __new__(cls, clients: TerminalClients, daemon: DaemonExchange) -> Self:
        self = super().__new__(cls)
        self._clients, self._daemon = clients, daemon
        self._callback = cls._ENTRY_ID
        return self

    async def connected(self) -> None:
        """Register fresh after every handshake; start no shell unasked.

        The entry carries no frame id: a frame id would make the display raise
        an existing frame locally, and a repeat click would never reach here.
        """
        result = await self._clients.client().callback.register(
            self._callback, "New terminal"
        )
        if isinstance(result, OpError):
            logger.warning("Terminal menu registration refused: %s", result.reason)

    async def clicked(self, callback: str) -> None:
        """Start a new shell on the daemon for each click on the entry.

        Raises:
            OSError: The daemon is unreachable, hung up or did not answer in time.
            SessionRefusedError: The daemon refused (the limit is reached) or
                answered nonsense.
        """
        if callback != self._callback:
            return
        reply = await asyncio.to_thread(self._daemon.ask, NewRequest(2))
        session = reply.result.get("session")
        if not isinstance(session, str) or not session:
            raise SessionRefusedError("luxd-pty answered new without a session")
        logger.info("Terminal %s started", session)
