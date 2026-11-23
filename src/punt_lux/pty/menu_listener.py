"""Held Hub connection owns the launcher callback and its renewal/reconnect."""

from __future__ import annotations

import asyncio
import logging
from typing import Self

from punt_lux.pty.menu_clients import TerminalClients
from punt_lux.pty.menu_projection import TerminalProjection

logger = logging.getLogger(__name__)


class TerminalMenu:
    _clients: TerminalClients
    _projection: TerminalProjection

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._clients = TerminalClients()
        self._projection = TerminalProjection(self._clients)
        return self

    async def serve(self) -> None:
        while True:
            try:
                listener = self._clients.listener(self._clicked, self._connected)
                await listener.listen()
            except OSError:
                logger.debug(
                    "Terminal launcher Hub unavailable; retrying", exc_info=True
                )
            await asyncio.sleep(2)

    async def _clicked(self, callback: str) -> None:
        try:
            await self._projection.clicked(callback)
        except OSError:
            logger.exception("Terminal menu click failed; PTY owner remains live")

    async def _connected(self) -> None:
        try:
            await self._projection.connected()
        except OSError:
            logger.exception(
                "Terminal launcher registration failed; listener remains live"
            )
