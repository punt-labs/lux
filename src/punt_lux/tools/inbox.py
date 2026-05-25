"""Per-connection inbox queues for MCP-side Agent Subscribe delivery.

The Hub writer for an MCP session puts each ``Hub.publish`` fan-out
onto a ``queue.SimpleQueue`` keyed by the session's ``ConnectionId``.
The ``recv`` MCP tool consumes one message per call; tests use
``drain_inbox`` to snapshot the full queue at once.
"""

from __future__ import annotations

import queue
import threading

from punt_lux.domain.hub import hub, hub_display
from punt_lux.domain.ids import ConnectionId
from punt_lux.protocol.messages.observer import ObserverMessage

__all__ = [
    "drain_inbox",
    "drop_session",
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
        if (existing := _inboxes.get(connection_id)) is not None:
            return existing
        _inboxes[connection_id] = queue.SimpleQueue()
        return _inboxes[connection_id]


def drain_inbox(connection_id: ConnectionId) -> tuple[ObserverMessage, ...]:
    """Snapshot then clear the connection's inbox; used by tests.

    Swaps the live queue with a fresh empty one under the lock so a
    concurrent producer's ``put`` lands in the new queue, never racing
    with the drain loop on the snapshot.
    """
    with _inboxes_lock:
        old = _inboxes.get(connection_id)
        if old is None:
            return ()
        _inboxes[connection_id] = queue.SimpleQueue()
    drained: list[ObserverMessage] = []
    while True:
        try:
            drained.append(old.get_nowait())
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
    """Bind an inbox writer and register the client; idempotent."""
    hub_display.register_client(connection_id)
    if hub.has_writer(connection_id):
        return
    # Ensure the inbox exists; the writer resolves the live queue per
    # call so a ``drain_inbox`` swap doesn't strand messages on the old
    # queue instance.
    inbox_for(connection_id)

    def _writer(message: ObserverMessage) -> None:
        inbox_for(connection_id).put(message)

    hub.register_writer(connection_id, _writer)


def drop_session(connection_id: ConnectionId) -> None:
    """Release the session's inbox queue. Idempotent.

    Called from the connection-disconnect cascade so the queue is not
    leaked when the WebSocket closes. Subsequent ``inbox_for`` calls for
    the same id create a fresh queue.
    """
    with _inboxes_lock:
        _inboxes.pop(connection_id, None)
