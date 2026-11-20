"""Terminal launcher metadata, never PTY/native state on the Hub loop."""

from __future__ import annotations

import logging
from typing import Self

from punt_lux.operations import OpError, RenderRequest
from punt_lux.ptyd.menu_clients import TerminalClients

logger = logging.getLogger(__name__)


class TerminalProjection:
    _clients: TerminalClients
    _opened: bool

    def __new__(cls, clients: TerminalClients) -> Self:
        self = super().__new__(cls)
        self._clients = clients
        self._opened = False
        return self

    async def connected(self) -> None:
        """Register fresh after every handshake; do not start an unsolicited shell.

        The entry is registered with the terminal frame's id, so a repeat click
        on a frame the user closed is reopened by the display itself rather than
        routed here as a scene.show that no-ops against the still-installed
        scene. Without the frame id the Clients-menu entry launches only once.
        """
        result = await self._clients.client().callback.register(
            "terminal", "Terminal", frame_id="terminal"
        )
        if isinstance(result, OpError):
            logger.warning("Terminal menu registration refused: %s", result.reason)
        if self._opened:
            await self.clicked("terminal")

    async def clicked(self, callback: str) -> None:
        if callback != "terminal":
            return
        request = RenderRequest(
            scene_id="terminal",
            title="Terminal",
            elements=[
                {
                    "kind": "terminal",
                    "id": "shell",
                    "session": "luxd-pty-terminal",
                    "height": 0,
                }
            ],
        )
        result = await self._clients.client().scene.show(request)
        if isinstance(result, OpError):
            logger.warning("Terminal launch refused: %s", result.reason)
        else:
            self._opened = True
