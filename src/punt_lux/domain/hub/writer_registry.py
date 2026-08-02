"""WriterRegistry — the outbound writer each connection is reachable through.

One connection has one writer: the callable that carries an ``ObserverMessage``
back to whoever is on the other end, bound when the connection comes online and
replaced when a later session of the same identity takes the connection over.

Because the connection is shared by successive sessions, a writer is dropped two
different ways, and the difference is who is doing the dropping.
:meth:`drop` is the connection going away entirely — everything under its id
goes. :meth:`release` is one session leaving a connection that may already
belong to its successor, so it unbinds only while the writer is still its own.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from punt_lux.domain.hub.subscription_registry import Handler
    from punt_lux.domain.ids import ConnectionId

__all__ = ["WriterRegistry"]


@final
class WriterRegistry:
    """The connections' outbound writers, keyed by ``ConnectionId``."""

    _writers: dict[ConnectionId, Handler]
    __slots__ = ("_writers",)

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._writers = {}
        return self

    def bind(self, connection_id: ConnectionId, writer: Handler) -> None:
        """Make ``writer`` the connection's outbound path. Idempotent overwrites."""
        self._writers[connection_id] = writer

    def drop(self, connection_id: ConnectionId) -> None:
        """Unbind the connection's writer, whoever installed it. No-op if absent."""
        self._writers.pop(connection_id, None)

    def release(self, connection_id: ConnectionId, writer: Handler) -> None:
        """Unbind the connection's writer only while it is still ``writer``.

        The departing session's own withdrawal: a session superseded while its
        socket wound down finds its successor bound here and leaves it alone.
        Bound methods of one session compare equal and of two sessions do not, so
        ``==`` is the ownership test.

        The compare and the removal are not locked, and do not need to be: a
        connection's writer is bound and released on luxd's single event loop —
        the listen leg's prologue and its await-free teardown — and the one binder
        on another thread (an MCP session's inbox writer) binds only when the
        connection has none.
        """
        if self._writers.get(connection_id) == writer:
            del self._writers[connection_id]

    def has(self, connection_id: ConnectionId) -> bool:
        """Whether the connection has a writer bound."""
        return connection_id in self._writers

    def writer_for(self, connection_id: ConnectionId) -> Handler:
        """The connection's writer; raise ``KeyError`` if it has none.

        A subscription registered against no writer would have no recipient, so
        this raises rather than answering with an absence the caller must re-check.
        """
        writer = self._writers.get(connection_id)
        if writer is None:
            msg = f"no writer registered for connection {connection_id!r}"
            raise KeyError(msg)
        return writer
