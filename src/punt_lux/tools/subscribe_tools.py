"""MCP tools for Agent Subscribe / Publish and menu callbacks."""

from __future__ import annotations

import asyncio

from punt_lux.commands import (
    CallbackPendingOps,
    CallbackRegisterOps,
    Ctx as CommandCtx,
    TopicOps,
    callback_pending as callback_pending_command,
    callback_register as callback_register_command,
    topic_publish as topic_publish_command,
    topic_recv as topic_recv_command,
    topic_subscribe as topic_subscribe_command,
    topic_unsubscribe as topic_unsubscribe_command,
)
from punt_lux.domain.hub.inbox import drain_inbox, inbox_for, next_event
from punt_lux.domain.ids import ConnectionId
from punt_lux.operations import PublishRequest, Scope
from punt_lux.operations.models.callback_fields import CallbackFields
from punt_lux.operations.models.callbacks import RegisterCallbackRequest
from punt_lux.tools import tools as _core
from punt_lux.tools._signal import signal
from punt_lux.tools.server import _session_key, mcp

__all__ = [
    "drain_inbox",
    "inbox_for",
    "next_event",
    "pending_callbacks",
    "publish",
    "recv",
    "register_callback",
    "subscribe",
    "unsubscribe",
]


def _scope() -> Scope:
    """Resolve the calling MCP session's operation scope."""
    return Scope(ConnectionId(_session_key.get()))


def _topic_ctx() -> CommandCtx[TopicOps]:
    """Build the topic command context around the calling session's identity."""
    return CommandCtx(ops=_core.OPERATIONS, identity=_core._identity())


@mcp.tool(name="topic_subscribe")
def subscribe(topic: str) -> str:
    """Subscribe the calling session to ``topic`` within its own scope.

    Returns ``"subscribed:<topic>"``. Declaration is implicit — the
    first subscribe (or publish) for a topic name in this session's
    scope declares it. Subscriptions never cross sessions.
    """
    return signal(
        asyncio.run(topic_subscribe_command(_topic_ctx(), topic, scope=_scope()))
    )


@mcp.tool(name="topic_unsubscribe")
def unsubscribe(topic: str) -> str:
    """Drop the calling session's subscription to ``topic``. No-op if absent."""
    return signal(
        asyncio.run(topic_unsubscribe_command(_topic_ctx(), topic, scope=_scope()))
    )


@mcp.tool(name="topic_publish")
def publish(topic: str, payload: dict[str, object] | None = None) -> str:
    """Fan ``payload`` out to ``topic``'s subscribers in the caller's scope.

    Returns ``"delivered:<count>"`` — the number of in-scope subscribers
    that received the message. A publish with no subscribers returns
    ``"delivered:0"`` and is otherwise a no-op.
    """
    request = PublishRequest(payload=payload or {})
    return signal(
        asyncio.run(topic_publish_command(_topic_ctx(), topic, request, scope=_scope()))
    )


@mcp.tool(name="topic_recv")
def recv() -> str:
    """Take the next business event waiting for the calling session, or none.

    Returns ``"event:<topic>:<json-payload>"`` for a published event the session
    is subscribed to, or ``"none"`` when the inbox is empty. Never blocks — it
    drains whatever is queued and returns; to wait, poll on your own schedule.
    Events come from ``Hub.publish`` scoped to this session; UI wire frames
    (button clicks, slider drags) are not delivered here.
    """
    return signal(asyncio.run(topic_recv_command(_topic_ctx(), scope=_scope())))


@mcp.tool(name="callback_pending")
def pending_callbacks() -> str:
    """Return the caller's held callback invocations without draining them.

    Returns ``"pending:<count>"``. A polling client peeks with this; the real
    delivery still runs on the listen leg's ``take`` drain.
    """
    ctx: CommandCtx[CallbackPendingOps] = CommandCtx(
        ops=_core.OPERATIONS, identity=_core._identity()
    )
    result = asyncio.run(callback_pending_command(ctx, scope=_scope()))
    return signal(result)


@mcp.tool(name="callback_register")
def register_callback(callback_id: str, label: str) -> str:
    """Register a menu callback; requires the caller to hold a listen leg + identify.

    Returns ``"registered:<callback_id>"``; dies with the session's lease.
    """
    ctx: CommandCtx[CallbackRegisterOps] = CommandCtx(
        ops=_core.OPERATIONS, identity=_core._identity()
    )
    request = RegisterCallbackRequest.parse(CallbackFields(callback_id, label))
    result = asyncio.run(callback_register_command(ctx, request, scope=_scope()))
    return signal(result)
