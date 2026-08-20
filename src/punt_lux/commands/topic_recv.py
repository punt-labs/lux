"""``topic recv`` -- take the next business event for the caller's session.

Text shape matches the shipped ``recv`` MCP tool byte-for-byte:
``"event:<topic>:<json-payload>"`` for a delivered event, ``"none"`` for an
empty inbox. Never blocks (see project memory
``blocking-ux-not-blocking-impl``) -- the caller polls on its own schedule.
"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Self, final

from punt_lux.commands._result import CommandResult

if TYPE_CHECKING:
    from punt_lux.commands._ports import Ctx, TopicOps
    from punt_lux.operations import Scope
    from punt_lux.operations.models.pubsub import Received


@final
class TopicRecvCommand:
    """Take the next business event waiting for the caller's session, or none."""

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    async def execute(self, ctx: Ctx[TopicOps], *, scope: Scope) -> Received:
        """Return the next event for ``scope`` (``event=None`` when the inbox is empty).

        Threaded because ``ctx.ops.receive`` runs synchronously against the
        inbox lock; the underlying `next_event` call is blocking I/O.
        """
        return await asyncio.to_thread(ctx.ops.receive, scope=scope)

    async def __call__(self, ctx: Ctx[TopicOps], *, scope: Scope) -> CommandResult:
        """Run :meth:`execute` and render its outcome into the shared envelope."""
        result = await self.execute(ctx, scope=scope)
        if result.event is None:
            return CommandResult(text="none", json_data={"event": None})
        payload = json.dumps(result.event.payload, sort_keys=True)
        return CommandResult(
            text=f"event:{result.event.topic}:{payload}",
            json_data={
                "event": {
                    "topic": result.event.topic,
                    "payload": dict(result.event.payload),
                }
            },
        )


topic_recv: TopicRecvCommand = TopicRecvCommand()
