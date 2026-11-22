"""Keep SDK streamable HTTP connections scoped to their Lux session registry."""

from __future__ import annotations

import logging
from contextvars import ContextVar
from typing import TYPE_CHECKING, ClassVar, Self, final

from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.shared.exceptions import MCPError
from mcp.types import UNSUPPORTED_PROTOCOL_VERSION
from mcp_types.version import HANDSHAKE_PROTOCOL_VERSIONS

from punt_lux.kernel.connection_id import ConnectionId
from punt_lux.mcp_session import SessionRegistry
from punt_lux.mcp_session_scope import McpSessionScope
from punt_lux.session_cleanup import SessionCleanup
from punt_lux.tools.server import current_session

if TYPE_CHECKING:
    from contextlib import AbstractAsyncContextManager, AsyncExitStack

    from mcp.server.context import CallNext, HandlerResult, ServerRequestContext
    from mcp.server.lowlevel import Server
    from mcp.server.transport_security import TransportSecuritySettings
    from starlette.types import Receive, Scope, Send

__all__ = ["LuxSessionManager"]

logger = logging.getLogger(__name__)


@final
class LuxSessionManager:
    """Bind each ASGI app's registry to the SDK tasks spawned by its manager."""

    _active: ClassVar[ContextVar[SessionRegistry | None]] = ContextVar(
        "lux_http_session_registry", default=None
    )
    _registry: SessionRegistry
    _sdk: StreamableHTTPSessionManager
    __slots__ = ("_registry", "_sdk")

    def __new__(
        cls,
        app: Server[object],
        security: TransportSecuritySettings,
        idle_timeout: float,
    ) -> Self:
        """Initialize a stateful SDK manager and its per-app session registry.

        Args:
            app: The low-level server to serve over HTTP.
            security: The transport's loopback Host and Origin allowlist.
            idle_timeout: Seconds of inactivity before an SDK session expires.
        """
        self = super().__new__(cls)
        self._sdk = StreamableHTTPSessionManager(
            app=app, security_settings=security, session_idle_timeout=idle_timeout
        )
        self._registry = SessionRegistry()
        if self.scope_session not in app.middleware:
            app.middleware.insert(0, self.scope_session)
        return self

    @property
    def session_count(self) -> int:
        """Return the number of live SDK sessions."""
        return self._registry.count

    def run(self) -> AbstractAsyncContextManager[None]:
        """Start the SDK task group within the daemon's lifespan."""
        return self._sdk.run()

    async def handle_request(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Serve an ASGI request with this manager's registry in task context."""
        token = self._active.set(self._registry)
        try:
            await self._sdk.handle_request(scope, receive, send)
        finally:
            self._active.reset(token)

    @classmethod
    async def scope_session(
        cls, ctx: ServerRequestContext[object], call_next: CallNext
    ) -> HandlerResult:
        """Preserve the initializing request's Hub scope for the connection's life.

        Args:
            ctx: The SDK request context.
            call_next: The remainder of the SDK middleware chain.

        Returns:
            The result from the next SDK handler.

        Raises:
            MCPError: The client requested sessionless HTTP.
        """
        registry = cls._active.get()
        if registry is None:  # The same low-level server also serves stdio.
            return await call_next(ctx)

        session = cls._stateful_session(ctx)
        result = await session.dispatch(ctx, call_next)
        if ctx.method == "initialize" and not session.initialize_accepted:
            cls._track_connection(registry, session.exit_stack)
        return result

    @staticmethod
    def _stateful_session(ctx: ServerRequestContext[object]) -> McpSessionScope:
        session = McpSessionScope(ctx)
        if not session.stateful:
            # Sessionless requests cannot own state that survives an exchange.
            raise MCPError(
                code=UNSUPPORTED_PROTOCOL_VERSION,
                message="Lux HTTP requires a stateful MCP session",
                data={"supported": sorted(HANDSHAKE_PROTOCOL_VERSIONS)},
            )
        return session

    @classmethod
    def _track_connection(
        cls, registry: SessionRegistry, exit_stack: AsyncExitStack
    ) -> None:
        key = current_session()
        registry.add(key)
        exit_stack.callback(cls._disconnect, registry, key)
        logger.info("MCP session connected")

    @staticmethod
    def _disconnect(registry: SessionRegistry, key: str) -> None:
        if registry.discard(key):
            SessionCleanup(ConnectionId(key)).run()
        logger.info("MCP session disconnected")
