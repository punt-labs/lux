"""Per-connection inbox queues for MCP-side Agent Subscribe delivery.

The Hub writer for an MCP session puts each ``Hub.publish`` fan-out
onto a ``queue.SimpleQueue`` keyed by the session's ``ConnectionId``.
The ``recv`` MCP tool consumes one message per call; tests use
``drain_inbox`` to snapshot the full queue at once.
"""

from __future__ import annotations

import queue
import threading

from punt_lux.domain.hub import hub
from punt_lux.domain.ids import ConnectionId
from punt_lux.protocol.messages.observer import ObserverMessage

__all__ = [
    "drain_inbox",
    "ensure_writer",
    "inbox_for",
    "next_event",
]


# SimpleQueue's get/put are thread-safe; the lock guards allocation of
# a new queue on first subscribe so two callers never see different
# instances for the same connection.
_inboxes: dict[ConnectionId, queue.SimpleQueue[ObserverMessage]] = {}
_inboxes_lock = threading.Lock()


def inbox_for(connection_id: ConnectionId) -> queue.SimpleQueue[ObserverMessage]:
    """Return (creating if needed) the connection's inbox queue."""
    with _inboxes_lock:
        existing = _inboxes.get(connection_id)
        if existing is not None:
            return existing
        fresh: queue.SimpleQueue[ObserverMessage] = queue.SimpleQueue()
        _inboxes[connection_id] = fresh
        return fresh


def drain_inbox(connection_id: ConnectionId) -> tuple[ObserverMessage, ...]:
    """Snapshot then clear the connection's inbox; used by tests."""
    with _inboxes_lock:
        inbox = _inboxes.get(connection_id)
    if inbox is None:
        return ()
    drained: list[ObserverMessage] = []
    while True:
        try:
            drained.append(inbox.get_nowait())
        except queue.Empty:
            break
    return tuple(drained)


def next_event(connection_id: ConnectionId, timeout: float) -> ObserverMessage | None:
    """Block for the next inbox message; return ``None`` on timeout."""
    inbox = inbox_for(connection_id)
    try:
        return inbox.get(timeout=timeout)
    except queue.Empty:
        return None


def ensure_writer(connection_id: ConnectionId) -> None:
    """Bind an inbox-putting writer for this connection on first use."""
    if hub.has_writer(connection_id):
        return
    inbox = inbox_for(connection_id)

    def _writer(message: ObserverMessage) -> None:
        inbox.put(message)

    hub.register_writer(connection_id, _writer)
