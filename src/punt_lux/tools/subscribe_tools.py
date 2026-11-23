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
from punt_lux.hub.inbox import drain_inbox, inbox_for, next_event
from punt_lux.tools import tools as _core
from punt_lux.tools._signal import signal
from punt_lux.tools.server import mcp
from punt_lux.tools.tools import scope
from punt_lux.wire.operations import PublishRequest
from punt_lux.wire.operations.callback_fields import CallbackFields
from punt_lux.wire.operations.callbacks import RegisterCallbackRequest

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


def _topic_ctx() -> CommandCtx[TopicOps]:
    """Build the topic command context around the calling session's identity."""
    return CommandCtx(ops=_core.OPERATIONS, identity=_core._identity())


@mcp.tool(name="topic_subscribe")
def subscribe(topic: str) -> str:
    """Subscribe the calling session to ``topic`` within its own scope.

    The first subscribe or publish declares the topic in this session's scope.

    Returns:
        ``"subscribed:<topic>"`` when the subscription is active.

    Raises:
        ToolError: If the topic is invalid or starts with the reserved ``lux.`` prefix.
    """
    return signal(
        asyncio.run(topic_subscribe_command(_topic_ctx(), topic, scope=scope()))
    )


@mcp.tool(name="topic_unsubscribe")
def unsubscribe(topic: str) -> str:
    """Drop the calling session's subscription without affecting other sessions.

    Returns:
        ``"unsubscribed:<topic>"``, even if there was no subscription.

    Raises:
        ToolError: If the topic is invalid or starts with the reserved ``lux.`` prefix.
    """
    return signal(
        asyncio.run(topic_unsubscribe_command(_topic_ctx(), topic, scope=scope()))
    )


@mcp.tool(name="topic_publish")
def publish(topic: str, payload: dict[str, object] | None = None) -> str:
    """Fan ``payload`` out to ``topic``'s subscribers in the caller's scope.

    Args:
        payload: JSON object to send; omit it to send an empty object.

    Returns:
        ``"delivered:<count>"`` with the number of in-scope recipients.

    Raises:
        ToolError: If the topic is invalid or starts with the reserved ``lux.`` prefix.
    """
    request = PublishRequest(payload=payload or {})
    return signal(
        asyncio.run(topic_publish_command(_topic_ctx(), topic, request, scope=scope()))
    )


@mcp.tool(name="topic_recv")
def recv() -> str:
    """Take the next business event waiting for the calling session, or none.

    Returns ``"event:<topic>:<json-payload>"`` for a waiting event, or ``"none"``
    when the inbox is empty. Never blocks — it drains whatever is queued and
    returns; to wait, poll on your own schedule. Two kinds of event land here:
    an app event from ``Hub.publish`` on a topic this session subscribed to, and
    a menu selection on the reserved ``lux.menu`` topic — when the user clicks an
    item you registered with ``menu_set``, a ``{"menu": ..., "item": "<id>"}``
    event arrives here with no ``topic_subscribe`` needed. Low-level scene-element
    wire frames (button clicks, slider drags) are still not delivered here.
    """
    return signal(asyncio.run(topic_recv_command(_topic_ctx(), scope=scope())))


@mcp.tool(name="callback_pending")
def pending_callbacks() -> str:
    """Return the caller's held callback invocations without draining them.

    Returns ``"pending:<count>"``. A polling client peeks with this; the real
    delivery still runs on the listen leg's ``take`` drain.
    """
    ctx: CommandCtx[CallbackPendingOps] = CommandCtx(
        ops=_core.OPERATIONS, identity=_core._identity()
    )
    result = asyncio.run(callback_pending_command(ctx, scope=scope()))
    return signal(result)


@mcp.tool(name="callback_register")
def register_callback(callback_id: str, label: str) -> str:
    """Register a menu callback until the caller's session lease ends.

    Returns:
        ``"registered:<callback_id>"`` when the callback is available.

    Raises:
        ToolError: If the fields are invalid or the caller has not identified
            itself and connected a listener for push delivery.
    """
    ctx: CommandCtx[CallbackRegisterOps] = CommandCtx(
        ops=_core.OPERATIONS, identity=_core._identity()
    )
    request = RegisterCallbackRequest.parse(CallbackFields(callback_id, label))
    result = asyncio.run(callback_register_command(ctx, request, scope=scope()))
    return signal(result)
