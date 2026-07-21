"""MCP tool surface for Agent Subscribe / Publish.

Four tools — ``subscribe``, ``unsubscribe``, ``publish``, ``recv`` — each an
adapter that parses its arguments, calls one operation on the Hub-owned pub-sub
surface scoped to the calling session, and formats the result. The subscription
scope, inbox, and fan-out live in the operations layer; the inbox helpers are
re-exported here for tests that snapshot a session's queue.
"""

from __future__ import annotations

import json

from punt_lux.domain.ids import ConnectionId
from punt_lux.operations import PublishRequest, Scope
from punt_lux.tools.inbox import drain_inbox, inbox_for, next_event
from punt_lux.tools.server import _session_key, mcp
from punt_lux.tools.tools import OPERATIONS

__all__ = [
    "drain_inbox",
    "inbox_for",
    "next_event",
    "publish",
    "recv",
    "subscribe",
    "unsubscribe",
]


def _scope() -> Scope:
    """Resolve the calling MCP session's operation scope."""
    return Scope(ConnectionId(_session_key.get()))


@mcp.tool()
def subscribe(topic: str) -> str:
    """Subscribe the calling session to ``topic`` within its own scope.

    Returns ``"subscribed:<topic>"``. Declaration is implicit — the
    first subscribe (or publish) for a topic name in this session's
    scope declares it. Subscriptions never cross sessions.
    """
    result = OPERATIONS.subscribe(topic, scope=_scope())
    return f"subscribed:{result.topic}"


@mcp.tool()
def unsubscribe(topic: str) -> str:
    """Drop the calling session's subscription to ``topic``. No-op if absent."""
    result = OPERATIONS.unsubscribe(topic, scope=_scope())
    return f"unsubscribed:{result.topic}"


@mcp.tool()
def publish(topic: str, payload: dict[str, object] | None = None) -> str:
    """Fan ``payload`` out to ``topic``'s subscribers in the caller's scope.

    Returns ``"delivered:<count>"`` — the number of in-scope subscribers
    that received the message. A publish with no subscribers returns
    ``"delivered:0"`` and is otherwise a no-op.
    """
    result = OPERATIONS.publish(
        topic, PublishRequest(payload=payload or {}), scope=_scope()
    )
    return f"delivered:{result.delivered}"


@mcp.tool()
def recv() -> str:
    """Take the next business event waiting for the calling session, or none.

    Returns ``"event:<topic>:<json-payload>"`` for a published event the session
    is subscribed to, or ``"none"`` when the inbox is empty. Never blocks — it
    drains whatever is queued and returns; to wait, poll on your own schedule.
    Events come from ``Hub.publish`` scoped to this session; UI wire frames
    (button clicks, slider drags) are not delivered here.
    """
    result = OPERATIONS.receive(scope=_scope())
    if result.event is None:
        return "none"
    payload = json.dumps(result.event.payload, sort_keys=True)
    return f"event:{result.event.topic}:{payload}"
