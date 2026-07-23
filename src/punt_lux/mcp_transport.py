"""luxd's MCP leg: streamable HTTP mounted at ``/mcp`` beside the REST routes.

It builds the SDK session manager over a :class:`SessionScopedServer` (so each
session runs the Hub cleanup cascade), wires the loopback policy's Host/Origin
security settings onto the transport, exposes the lifespan the parent app must
enter to start the session manager's task group, and mounts the ``/mcp`` route
whose endpoint resolves the session identity and refuses the reserved REST key.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Self, cast, final

from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.routing import Route

from punt_lux.mcp_endpoint import McpAsgiApp
from punt_lux.mcp_session import SessionRegistry, SessionScopedServer
from punt_lux.tools import mcp
from punt_lux.transport_policy import LoopbackTransportPolicy

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Callable
    from contextlib import AbstractAsyncContextManager

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

    _registry: SessionRegistry
    _manager: StreamableHTTPSessionManager
    _endpoint: McpAsgiApp
    __slots__ = ("_endpoint", "_manager", "_registry")

    def __new__(cls, policy: LoopbackTransportPolicy | None = None) -> Self:
        self = super().__new__(cls)
        policy = policy or LoopbackTransportPolicy()
        self._registry = SessionRegistry()
        scoped = SessionScopedServer(cls._fastmcp_server(), self._registry)
        self._manager = StreamableHTTPSessionManager(
            app=cast("MCPServer[object, object]", scoped),
            security_settings=policy.security_settings(),
            session_idle_timeout=SESSION_IDLE_TIMEOUT_SECONDS,
        )
        self._endpoint = McpAsgiApp(self._manager)
        return self

    @staticmethod
    def _fastmcp_server() -> MCPServer[object, object]:
        """Resolve FastMCP's low-level MCP server (private API; guard on upgrades)."""
        server = getattr(mcp, "_mcp_server", None)
        if server is None:
            msg = "FastMCP._mcp_server not found; this private API may have changed."
            raise RuntimeError(msg)
        return cast("MCPServer[object, object]", server)

    @staticmethod
    def _fastmcp_lifespan() -> Callable[[], AbstractAsyncContextManager[object]]:
        """Resolve FastMCP's lifespan manager (private API; guard on upgrades)."""
        manager = getattr(mcp, "_lifespan_manager", None)
        if manager is None:
            msg = "FastMCP._lifespan_manager not found; private API may have changed."
            raise RuntimeError(msg)
        return cast("Callable[[], AbstractAsyncContextManager[object]]", manager)

    @property
    def session_count(self) -> int:
        """How many MCP sessions are live — the health probe's ``sessions`` field."""
        return self._registry.count

    @asynccontextmanager
    async def lifespan(self) -> AsyncGenerator[None]:
        """Enter FastMCP's lifespan and start the session manager's task group.

        The parent app must run inside this, or the SDK's session manager raises
        because its task group was never initialized.
        """
        async with self._fastmcp_lifespan()(), self._manager.run():
            yield

    def mount(self, app: FastAPI) -> None:
        """Add the ``/mcp`` streamable-HTTP route to the parent app."""
        app.router.routes.append(
            Route(MCP_PATH, endpoint=self._endpoint, methods=["GET", "POST", "DELETE"])
        )
