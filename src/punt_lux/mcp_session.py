"""Per-session lifecycle for luxd's streamable-HTTP MCP leg.

The mcp SDK's session manager drives each MCP session's message loop by calling
``run`` once per session on the server object it was handed. luxd hands it a
:class:`SessionScopedServer` instead of the bare server so each session runs the
Hub connect/cleanup cascade: it registers on entry and, on exit, drops its menu
items, cascades the connection disconnect (scenes, subscriptions, writer,
inbox), and deregisters.

The session's :class:`ConnectionId` is read from the current-session accessor,
which the transport route binds from ``?session_key=`` before the session's task
is spawned, so the copied task context carries the right identity.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.hub import disconnect_connection
from punt_lux.domain.hub.inbox import drop_session
from punt_lux.domain.ids import ConnectionId
from punt_lux.operations import Scope
from punt_lux.tools.server import current_session
from punt_lux.tools.tools import OPERATIONS

if TYPE_CHECKING:
    from anyio.streams.memory import (
        MemoryObjectReceiveStream,
        MemoryObjectSendStream,
    )
    from mcp.server.lowlevel import Server as MCPServer
    from mcp.server.models import InitializationOptions
    from mcp.shared.message import SessionMessage

logger = logging.getLogger(__name__)

__all__ = ["SessionRegistry", "SessionScopedServer"]


@final
class SessionRegistry:
    """The live set of MCP session keys, for the health probe's session count."""

    _active: set[str]
    __slots__ = ("_active",)

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._active = set()
        return self

    def add(self, key: str) -> None:
        """Record a session as live."""
        self._active.add(key)

    def discard(self, key: str) -> None:
        """Forget a session; idempotent."""
        self._active.discard(key)

    @property
    def count(self) -> int:
        """How many MCP sessions are live right now."""
        return len(self._active)


@final
class SessionScopedServer:
    """Wrap the MCP server so each streamable-HTTP session runs the Hub cascade.

    One instance wraps the process-wide MCP server; the session manager calls
    :meth:`run` once per session, each in its own task, so the per-session
    accounting and cleanup are re-entrant and keyed by the session's own
    ``_session_key`` context value.
    """

    _inner: MCPServer[object, object]
    _registry: SessionRegistry
    __slots__ = ("_inner", "_registry")

    def __new__(
        cls, inner: MCPServer[object, object], registry: SessionRegistry
    ) -> Self:
        self = super().__new__(cls)
        self._inner = inner
        self._registry = registry
        return self

    def create_initialization_options(self) -> InitializationOptions:
        """Proxy the MCP handshake options through to the wrapped server."""
        return self._inner.create_initialization_options()

    async def run(
        self,
        read_stream: MemoryObjectReceiveStream[SessionMessage | Exception],
        write_stream: MemoryObjectSendStream[SessionMessage],
        initialization_options: InitializationOptions,
        *,
        stateless: bool = False,
    ) -> None:
        """Run one MCP session, bracketing it with the Hub connect/cleanup cascade."""
        key = current_session()
        connection_id = ConnectionId(key)
        self._registry.add(key)
        logger.info("MCP session connected: session_key=%s", key)
        try:
            await self._inner.run(
                read_stream,
                write_stream,
                initialization_options,
                stateless=stateless,
            )
        finally:
            self._registry.discard(key)
            # Two independent, idempotent cleanups: drop the session's menu items
            # (re-pushed to the display via the replicator) and cascade the
            # connection disconnect (scenes, subscriptions, writer, inbox).
            OPERATIONS.drop_session(Scope(connection_id))
            disconnect_connection(connection_id, drop_session)
            logger.info("MCP session disconnected: session_key=%s", key)
