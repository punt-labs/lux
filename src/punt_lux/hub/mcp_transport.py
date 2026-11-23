"""luxd's MCP leg: streamable HTTP mounted at ``/mcp`` beside the REST routes.

It uses the SDK session manager with per-connection Hub cleanup, applies the
loopback policy's Host/Origin checks, exposes the lifespan the parent app must
enter to start the session manager's task group, and mounts the ``/mcp`` route
whose endpoint resolves the session identity and refuses the reserved REST key.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Self, cast, final

from starlette.routing import Route

from punt_lux.hub.mcp_endpoint import McpAsgiApp
from punt_lux.hub.mcp_session_manager import LuxSessionManager
from punt_lux.hub.transport_policy import LoopbackTransportPolicy
from punt_lux.tools import mcp

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from fastapi import FastAPI
    from mcp.server.lowlevel import Server as MCPServer

__all__ = ["McpHttpTransport"]

MCP_PATH = "/mcp"

# Reap a vanished client's session (kill -9, dropped socket) 30 min after its
# last activity so its Hub-side scenes/menus/subscriptions/inbox cannot leak
# until restart — the value the mcp SDK session-manager docstring recommends.
SESSION_IDLE_TIMEOUT_SECONDS = 1800.0


@final
class McpHttpTransport:
    """luxd's streamable-HTTP MCP leg — session manager, lifespan, and route."""

    _manager: LuxSessionManager
    _endpoint: McpAsgiApp
    __slots__ = ("_endpoint", "_manager")

    def __new__(cls) -> Self:
        """Configure the MCP HTTP app with the daemon's loopback policy."""
        self = super().__new__(cls)
        self._manager = LuxSessionManager(
            cls._fastmcp_server(),
            LoopbackTransportPolicy().security_settings(),
            SESSION_IDLE_TIMEOUT_SECONDS,
        )
        self._endpoint = McpAsgiApp(self._manager)
        return self

    @staticmethod
    def _fastmcp_server() -> MCPServer[object]:
        """Resolve FastMCP's low-level MCP server."""
        server = getattr(mcp, "_mcp_server", None)
        if server is None:
            msg = "FastMCP._mcp_server not found; this private API may have changed."
            raise RuntimeError(msg)
        return cast("MCPServer[object]", server)

    @property
    def session_count(self) -> int:
        """How many MCP sessions are live — the health probe's ``sessions`` field."""
        return self._manager.session_count

    @asynccontextmanager
    async def lifespan(self) -> AsyncGenerator[None]:
        """Enter FastMCP's lifespan and start the session manager's task group.

        The parent app must run inside this, or the SDK's session manager raises
        because its task group was never initialized.
        """
        async with self._manager.run():
            yield

    def mount(self, app: FastAPI) -> None:
        """Add the ``/mcp`` streamable-HTTP route to the parent app."""
        app.router.routes.append(
            Route(MCP_PATH, endpoint=self._endpoint, methods=["GET", "POST", "DELETE"])
        )
