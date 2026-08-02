"""MCP tool surface for Agent Subscribe / Publish and menu callbacks.

The pub-sub tools — ``subscribe``, ``unsubscribe``, ``publish``, ``recv`` — each
parse their arguments, call one operation on the Hub-owned pub-sub surface scoped
to the calling session, and format the result. The two menu-callback tools are
the session's own end of the callback model: ``register_callback`` puts a menu
entry in the bar under the calling session's identity, and that entry's clicks
arrive on the session's listen leg, never on an MCP read. All are session-scoped
tools that share the same ``_scope`` resolution; the subscription scope, inbox,
and fan-out live in the operations layer, and the inbox helpers are re-exported
here for tests that snapshot a session's queue.
"""

from __future__ import annotations

import json

from punt_lux.domain.hub.inbox import drain_inbox, inbox_for, next_event
from punt_lux.domain.ids import ConnectionId
from punt_lux.operations import OpError, PublishRequest, Scope
from punt_lux.operations.models.callbacks import RegisterCallbackRequest
from punt_lux.tools.server import _session_key, mcp
from punt_lux.tools.tools import OPERATIONS

__all__ = [
    "drain_inbox",
    "inbox_for",
    "next_event",
    "publish",
    "recv",
    "register_callback",
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


@mcp.tool()
def register_callback(callback_id: str, label: str) -> str:
    """Register one menu callback the calling session owns and services.

    ``label`` is the entry the display shows under this session's submenu;
    ``callback_id`` is the id its clicks carry back.

    Two things must be true of the caller, and both are refused as
    ``"error: <reason>"`` rather than half-granted. The connection must hold
    luxd's listen leg, because a click is delivered by push and a connection with
    no leg would never learn of it — an MCP session on its own has none, so this
    tool is for a caller whose process holds one (an applet does, and
    registers its session's entries itself). And the session must have identified,
    the same challenge REST's anonymous writes receive.

    On success returns ``"registered:<callback_id>"`` and the replicator pushes the
    updated bar. A callback lives on its session and leaves the menu when the
    session's lease lapses, so there is no separate withdrawal — disconnecting or
    letting the lease expire removes it.
    """
    result = OPERATIONS.register_callback(
        RegisterCallbackRequest.parse(callback_id=callback_id, label=label),
        scope=_scope(),
    )
    if isinstance(result, OpError):
        return f"error: {result.reason}"
    return f"registered:{callback_id}"
