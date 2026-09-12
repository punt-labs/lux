"""``topic subscribe`` -- subscribe the caller's session to a topic."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Self, final

from punt_lux.commands._faults import render_error
from punt_lux.commands._result import CommandResult
from punt_lux.operations import OpError

if TYPE_CHECKING:
    from punt_lux.commands._ports import Ctx, TopicOps
    from punt_lux.operations import Scope
    from punt_lux.operations.models.pubsub_acks import Subscribed


@final
class TopicSubscribeCommand:
    """Subscribe the caller's session to a topic."""

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    async def execute(
        self, ctx: Ctx[TopicOps], topic: str, *, scope: Scope
    ) -> Subscribed | OpError:
        """Subscribe ``scope`` to ``topic`` and return the typed ack or refusal."""
        return await asyncio.to_thread(ctx.ops.subscribe, topic, scope=scope)

    async def __call__(
        self, ctx: Ctx[TopicOps], topic: str, *, scope: Scope
    ) -> CommandResult:
        """Run :meth:`execute` and render its outcome into the shared envelope."""
        result = await self.execute(ctx, topic, scope=scope)
        if isinstance(result, OpError):
            return render_error(result)
        return CommandResult(
            text=f"subscribed:{result.topic}", json_data={"topic": result.topic}
        )


topic_subscribe: TopicSubscribeCommand = TopicSubscribeCommand()
