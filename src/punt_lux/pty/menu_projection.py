"""Terminal launcher metadata, never PTY/native state on the Hub loop."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Self

from punt_lux.pty.session_starter import SessionStarter
from punt_lux.wire.operations import OpError, RenderRequest

if TYPE_CHECKING:
    from punt_lux.pty.menu_clients import TerminalClients

logger = logging.getLogger(__name__)
_SHELL: dict[str, object] = {"kind": "terminal", "id": "shell", "height": 0}


class TerminalProjection:
    _clients: TerminalClients
    _starter: SessionStarter
    _session: str

    def __new__(cls, clients: TerminalClients) -> Self:
        self = super().__new__(cls)
        self._clients = clients
        self._starter = SessionStarter.local()
        self._session = ""
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
        if self._session:
            await self._show()

    async def clicked(self, callback: str) -> None:
        if callback != "terminal":
            return
        self._session = await asyncio.to_thread(self._starter.start)
        await self._show()

    async def _show(self) -> None:
        shell = _SHELL | {"session": self._session}
        request = RenderRequest(scene_id="terminal", title="Terminal", elements=[shell])
        result = await self._clients.client().scene.show(request)
        if isinstance(result, OpError):
            logger.warning("Terminal launch refused: %s", result.reason)
            self._session = ""
