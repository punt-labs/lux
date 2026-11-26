"""Held Hub connection owns the launcher callback; the keeper owns the windows."""

from __future__ import annotations

import asyncio
import logging
from typing import Self

from punt_lux.pty.daemon_exchange import DaemonExchange, SessionRefusedError
from punt_lux.pty.menu_clients import TerminalClients
from punt_lux.pty.menu_projection import TerminalProjection
from punt_lux.pty.terminal_keeper import TerminalKeeper
from punt_lux.pty.terminal_windows import TerminalWindows

logger = logging.getLogger(__name__)


class TerminalMenu:
    _clients: TerminalClients
    _projection: TerminalProjection
    _keeper: TerminalKeeper

    def __new__(cls, clients: TerminalClients, daemon: DaemonExchange) -> Self:
        self = super().__new__(cls)
        self._clients = clients
        self._projection = TerminalProjection(clients, daemon)
        self._keeper = TerminalKeeper(daemon, TerminalWindows(clients))
        return self

    @classmethod
    def local(cls) -> Self:
        """Serve the daemon this helper was started by, over the normal Hub."""
        return cls(TerminalClients(), DaemonExchange.local())

    async def serve(self) -> None:
        keeper = asyncio.create_task(self._keeper.serve())
        try:
            while True:
                try:
                    listener = self._clients.listener(self._clicked, self._connected)
                    await listener.listen()
                except OSError:
                    logger.debug(
                        "Terminal launcher Hub unavailable; retrying", exc_info=True
                    )
                await asyncio.sleep(2)
        finally:
            keeper.cancel()
            await asyncio.gather(keeper, return_exceptions=True)

    async def _clicked(self, callback: str) -> None:
        try:
            await self._projection.clicked(callback)
        except (OSError, SessionRefusedError):
            logger.exception("Terminal menu click failed; PTY owner remains live")

    async def _connected(self) -> None:
        # A restarted Hub holds none of the scenes the keeper showed.
        self._keeper.resync()
        try:
            await self._projection.connected()
        except (OSError, SessionRefusedError):
            logger.exception(
                "Terminal launcher registration failed; listener remains live"
            )
