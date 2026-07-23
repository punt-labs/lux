"""luxd's MCP leg: streamable HTTP mounted beside the REST routes.

luxd serves MCP over the mcp SDK's streamable-HTTP transport on the same FastAPI
app and uvicorn port as the typed REST API, at ``/mcp``. This module owns that
leg: it builds the SDK session manager over a :class:`SessionScopedServer` (so
each session runs the Hub cleanup cascade), wires the loopback policy's security
settings onto the transport (Host/Origin validation), exposes the lifespan the
parent app must enter so the session manager's task group is live, and mounts
the ``/mcp`` route whose endpoint resolves the session identity and refuses the
reserved REST key.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Self, cast, final

from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route

from punt_lux.mcp_session import SessionRegistry, SessionScopedServer
from punt_lux.session_key import SessionKey
from punt_lux.tools import mcp
from punt_lux.tools.server import bind_session, unbind_session
from punt_lux.transport_policy import LoopbackTransportPolicy

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Callable
    from contextlib import AbstractAsyncContextManager

    from fastapi import FastAPI
    from mcp.server.lowlevel import Server as MCPServer
    from starlette.types import Receive, Scope, Send

logger = logging.getLogger(__name__)

__all__ = ["McpHttpTransport"]

MCP_PATH = "/mcp"


def _fastmcp_server() -> MCPServer[object, object]:
    """Resolve FastMCP's low-level MCP server (private API; guard on upgrades)."""
    server = getattr(mcp, "_mcp_server", None)
    if server is None:
        msg = "FastMCP._mcp_server not found; this private API may have changed."
        raise RuntimeError(msg)
    return cast("MCPServer[object, object]", server)


def _fastmcp_lifespan() -> Callable[[], AbstractAsyncContextManager[object]]:
    """Resolve FastMCP's lifespan manager (private API; guard on upgrades)."""
    manager = getattr(mcp, "_lifespan_manager", None)
    if manager is None:
        msg = "FastMCP._lifespan_manager not found; this private API may have changed."
        raise RuntimeError(msg)
    return cast("Callable[[], AbstractAsyncContextManager[object]]", manager)


@final
class McpAsgiApp:
    """The ``/mcp`` endpoint: resolve the session identity, then serve the request.

    A ``?session_key=`` value becomes the session's :class:`ConnectionId`; a value
    colliding with the reserved REST scope is refused with 403, because sharing it
    would cross scene, menu, and topic ownership and the session's disconnect
    cascade would destroy REST-created state. The identity is set on the
    ``_session_key`` ContextVar before the manager spawns the session's task, so
    the copied task context carries it to the tools and the cleanup cascade.
    """

    _manager: StreamableHTTPSessionManager
    __slots__ = ("_manager",)

    def __new__(cls, manager: StreamableHTTPSessionManager) -> Self:
        self = super().__new__(cls)
        self._manager = manager
        return self

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        session = SessionKey.from_request(
            Request(scope).query_params.get("session_key", "")
        )
        if session.is_reserved:
            logger.warning("Rejected reserved session_key=%s", session.value)
            refusal = Response(
                "session_key is reserved for the REST surface", status_code=403
            )
            await refusal(scope, receive, send)
            return
        token = bind_session(session.value)
        try:
            await self._manager.handle_request(scope, receive, send)
        finally:
            unbind_session(token)


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
        scoped = SessionScopedServer(_fastmcp_server(), self._registry)
        self._manager = StreamableHTTPSessionManager(
            app=cast("MCPServer[object, object]", scoped),
            security_settings=policy.security_settings(),
        )
        self._endpoint = McpAsgiApp(self._manager)
        return self

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
        async with _fastmcp_lifespan()(), self._manager.run():
            yield

    def mount(self, app: FastAPI) -> None:
        """Add the ``/mcp`` streamable-HTTP route to the parent app."""
        app.router.routes.append(
            Route(MCP_PATH, endpoint=self._endpoint, methods=["GET", "POST", "DELETE"])
        )
