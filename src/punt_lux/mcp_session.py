"""Per-session lifecycle for luxd's streamable-HTTP MCP leg.

The mcp SDK's session manager drives each MCP session's message loop by calling
``run`` once per session on the server object it was handed. luxd hands it a
:class:`SessionScopedServer` instead of the bare server so each session runs the
Hub connect/cleanup cascade: it registers on entry and always deregisters on
exit. Two sessions may share one ``session_key`` and therefore one Hub
connection scope; the teardown that drops the key's menu items and cascades the
connection disconnect (scenes, subscriptions, writer, inbox) runs only when the
last same-key session leaves, so one session's exit never wipes a live peer's
state.

The session's :class:`ConnectionId` is read from the current-session accessor,
which the transport route binds from ``?session_key=`` before the session's task
is spawned, so the copied task context carries the right identity.
"""

from __future__ import annotations

import logging
from collections import Counter
from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.ids import ConnectionId
from punt_lux.session_cleanup import SessionCleanup
from punt_lux.tools.server import current_session

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
    """The live MCP sessions, counted per instance for the health probe.

    Keyed by session key but summed by instance: two sessions under one key
    count as two, and the first to disconnect leaves the peer counted (a set
    would drop the peer). Cleanup keys on the ``ConnectionId``, so :meth:`discard`
    reports whether its call drained the key — the last session out is the one
    that may tear the shared scope down.
    """

    _active: Counter[str]
    __slots__ = ("_active",)

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._active = Counter()
        return self

    def add(self, key: str) -> None:
        """Record one live session under ``key``."""
        self._active[key] += 1

    def discard(self, key: str) -> bool:
        """Drop one live session under ``key``; report whether the key is drained.

        Returns ``True`` when no live session remains under ``key`` (the last
        same-key session left, so its shared scope may now be torn down) and
        ``False`` while a peer is still counted. Idempotent: discarding an absent
        or already-drained key is a no-op that reports ``True``.
        """
        self._active[key] -= 1
        # Unary plus keeps only positive counts — drops a drained/absent key.
        self._active = +self._active
        return key not in self._active

    @property
    def count(self) -> int:
        """How many MCP sessions are live right now."""
        return self._active.total()


@final
class SessionScopedServer:
    """Wrap the MCP server so each streamable-HTTP session runs the Hub cascade.

    One instance wraps the process-wide MCP server; the session manager calls
    :meth:`run` once per session, each in its own task, so the per-session
    accounting is re-entrant and keyed by the session's own ``_session_key``
    context value. Sessions sharing a key share one Hub connection scope, so
    :meth:`run` deregisters every session on exit but only runs the Hub cleanup
    cascade when the registry reports the last same-key session has left.
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
            if self._registry.discard(key):
                SessionCleanup(connection_id).run(key)
            logger.info("MCP session disconnected: session_key=%s", key)
