"""``topic unsubscribe`` -- drop the caller's subscription to a topic."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Self, final

from punt_lux.commands._result import CommandResult

if TYPE_CHECKING:
    from punt_lux.commands._ports import Ctx, TopicOps
    from punt_lux.operations import Scope
    from punt_lux.operations.models.pubsub_acks import Unsubscribed


@final
class TopicUnsubscribeCommand:
    """Drop the caller's subscription to a topic; a no-op if absent."""

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    async def execute(
        self, ctx: Ctx[TopicOps], topic: str, *, scope: Scope
    ) -> Unsubscribed:
        """Unsubscribe ``scope`` from ``topic`` and return the typed ack."""
        return await asyncio.to_thread(ctx.ops.unsubscribe, topic, scope=scope)

    async def __call__(
        self, ctx: Ctx[TopicOps], topic: str, *, scope: Scope
    ) -> CommandResult:
        """Run :meth:`execute` and render its outcome into the shared envelope."""
        result = await self.execute(ctx, topic, scope=scope)
        return CommandResult(
            text=f"unsubscribed:{result.topic}", json_data={"topic": result.topic}
        )


topic_unsubscribe: TopicUnsubscribeCommand = TopicUnsubscribeCommand()
