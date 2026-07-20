"""MCP tool surface for Agent Subscribe / Publish.

Four tools — ``subscribe``, ``unsubscribe``, ``publish``, ``recv`` — each
scoped to the calling MCP session's ``ConnectionId``. Inbox queueing and
the session's writer registration live in :mod:`punt_lux.tools.inbox`.
"""

from __future__ import annotations

import json

from punt_lux.domain.hub import hub
from punt_lux.domain.ids import ConnectionId, Topic
from punt_lux.tools.inbox import drain_inbox, ensure_writer, inbox_for, next_event
from punt_lux.tools.server import _session_key, mcp

__all__ = [
    "drain_inbox",
    "inbox_for",
    "next_event",
    "publish",
    "recv",
    "subscribe",
    "unsubscribe",
]


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
    ensure_writer(connection_id)
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
def publish(topic: str, payload: dict[str, object] | None = None) -> str:
    """Fan ``payload`` out to ``topic``'s subscribers in the caller's scope.

    Returns ``"delivered:<count>"`` — the number of in-scope subscribers
    that received the message. A publish with no subscribers returns
    ``"delivered:0"`` and is otherwise a no-op.
    """
    connection_id = _connection_id()
    ensure_writer(connection_id)
    delivered = hub.publish(connection_id, Topic(topic), payload or {})
    return f"delivered:{delivered}"


@mcp.tool()
def recv() -> str:
    """Take the next business event waiting for the calling session, or none.

    Returns ``"event:<topic>:<json-payload>"`` for a published event the session
    is subscribed to, or ``"none"`` when the inbox is empty. Never blocks — it
    drains whatever is queued and returns; to wait, poll on your own schedule.
    Events come from ``Hub.publish`` scoped to this session; UI wire frames
    (button clicks, slider drags) are not delivered here.
    """
    connection_id = _connection_id()
    ensure_writer(connection_id)
    message = next_event(connection_id, timeout=0.0)
    if message is None:
        return "none"
    return f"event:{message.topic}:{json.dumps(dict(message.payload), sort_keys=True)}"
