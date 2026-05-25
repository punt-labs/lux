"""MCP tool surface for Agent Subscribe / Publish.

Three tools — ``subscribe``, ``unsubscribe``, ``publish`` — each scoped
to the calling MCP session's ``ConnectionId``. The session's writer is
an in-memory deque the Hub fans out to; downstream commits replace it
with the connection's outbound wire writer.
"""

from __future__ import annotations

import threading
from collections import deque
from typing import Any

from punt_lux.domain.hub import hub
from punt_lux.domain.ids import ConnectionId, Topic
from punt_lux.protocol.messages.observer import ObserverMessage
from punt_lux.tools.server import _session_key, mcp

__all__ = [
    "drain_inbox",
    "inbox_for",
    "publish",
    "subscribe",
    "unsubscribe",
]


# Per-connection inbox queues. The Hub's writer for an MCP connection
# appends ObserverMessages here; a subsequent recv() (lands in commit 7)
# drains them. The lock guards concurrent append / drain across the
# lifespan thread and tool threads — deque.append is atomic, but
# allocation of a new deque on first subscribe is not.
_inboxes: dict[ConnectionId, deque[ObserverMessage]] = {}
_inboxes_lock = threading.Lock()


def inbox_for(connection_id: ConnectionId) -> deque[ObserverMessage]:
    """Return (creating if needed) the connection's inbox queue."""
    with _inboxes_lock:
        existing = _inboxes.get(connection_id)
        if existing is not None:
            return existing
        fresh: deque[ObserverMessage] = deque()
        _inboxes[connection_id] = fresh
        return fresh


def drain_inbox(connection_id: ConnectionId) -> tuple[ObserverMessage, ...]:
    """Snapshot then clear the connection's inbox; used by recv()-style polls."""
    with _inboxes_lock:
        inbox = _inboxes.get(connection_id)
        if inbox is None:
            return ()
        drained = tuple(inbox)
        inbox.clear()
        return drained


def _ensure_writer(connection_id: ConnectionId) -> None:
    """Bind an inbox-appending writer for this connection on first use."""
    if hub.has_writer(connection_id):
        return
    inbox = inbox_for(connection_id)

    def _writer(message: ObserverMessage) -> None:
        inbox.append(message)

    hub.register_writer(connection_id, _writer)


def _connection_id() -> ConnectionId:
    """Resolve the current MCP session's ConnectionId."""
    return ConnectionId(_session_key.get())


@mcp.tool()
def subscribe(topic: str) -> str:
    """Subscribe the calling session to ``topic`` within its own scope.

    Returns ``"subscribed:<topic>"``. Declaration is implicit — the
    first subscribe (or publish) for a topic name in this session's
    scope declares it. Subscriptions never cross sessions.
    """
    connection_id = _connection_id()
    _ensure_writer(connection_id)
    hub.subscribe(connection_id, Topic(topic))
    return f"subscribed:{topic}"


@mcp.tool()
def unsubscribe(topic: str) -> str:
    """Drop the calling session's subscription to ``topic``. No-op if absent."""
    connection_id = _connection_id()
    if not hub.has_writer(connection_id):
        return f"unsubscribed:{topic}"
    hub.unsubscribe(connection_id, Topic(topic))
    return f"unsubscribed:{topic}"


@mcp.tool()
def publish(topic: str, payload: dict[str, Any] | None = None) -> str:
    """Fan ``payload`` out to ``topic``'s subscribers in the caller's scope.

    Returns ``"delivered:<count>"`` — the number of in-scope subscribers
    that received the message. A publish with no subscribers returns
    ``"delivered:0"`` and is otherwise a no-op.
    """
    connection_id = _connection_id()
    _ensure_writer(connection_id)
    delivered = hub.publish(connection_id, Topic(topic), payload or {})
    return f"delivered:{delivered}"
