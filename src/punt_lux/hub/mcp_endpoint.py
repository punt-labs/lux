"""The ``/mcp`` request endpoint: resolve the request's contact, then serve."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from starlette.requests import Request

from punt_lux.hub.session_key import SessionKey
from punt_lux.kernel.client_host import ClientHost
from punt_lux.tools.server import bind_session, unbind_session

if TYPE_CHECKING:
    from starlette.types import Receive, Scope, Send

    from punt_lux.hub.mcp_session_manager import LuxSessionManager

__all__ = ["McpAsgiApp"]


@final
class McpAsgiApp:
    """The ``/mcp`` endpoint: resolve the request's contact, then serve.

    Bind the proposed ``?session_key=`` (or a generated handle) and observed
    socket peer to the request context. The manager retains the contact from
    initialization for subsequent tool calls and cleanup.
    """

    _manager: LuxSessionManager
    __slots__ = ("_manager",)

    def __new__(cls, manager: LuxSessionManager) -> Self:
        """Bind the streamable-HTTP MCP manager to its ASGI endpoint."""
        self = super().__new__(cls)
        self._manager = manager
        return self

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Serve the MCP request under its session context."""
        request = Request(scope)
        session = SessionKey.from_request(request.query_params.get("session_key", ""))
        binding = bind_session(session.value, ClientHost.of_connection(request))
        try:
            await self._manager.handle_request(scope, receive, send)
        finally:
            unbind_session(binding)
