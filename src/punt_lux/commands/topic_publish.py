"""``topic publish`` -- fan a payload out to a topic's subscribers.

Text shape matches the shipped ``publish`` MCP tool byte-for-byte:
``"delivered:<count>"`` on success (a publish with no subscribers is still
``"delivered:0"`` -- both outcomes are normal per PY-EH-4).
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Self, final

from punt_lux.commands._result import CommandResult

if TYPE_CHECKING:
    from punt_lux.commands._ports import Ctx, TopicOps
    from punt_lux.operations import Scope
    from punt_lux.operations.models.pubsub import PublishRequest
    from punt_lux.operations.models.pubsub_acks import Published


@final
class TopicPublishCommand:
    """Fan a payload out to a topic's in-scope subscribers."""

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    async def execute(
        self,
        ctx: Ctx[TopicOps],
        topic: str,
        request: PublishRequest,
        *,
        scope: Scope,
    ) -> Published:
        """Publish ``request`` to ``topic`` in ``scope`` and return the typed ack."""
        return await asyncio.to_thread(ctx.ops.publish, topic, request, scope=scope)

    async def __call__(
        self,
        ctx: Ctx[TopicOps],
        topic: str,
        request: PublishRequest,
        *,
        scope: Scope,
    ) -> CommandResult:
        """Run :meth:`execute` and render its outcome into the shared envelope."""
        result = await self.execute(ctx, topic, request, scope=scope)
        return CommandResult(
            text=f"delivered:{result.delivered}",
            json_data={"topic": topic, "delivered": result.delivered},
        )


topic_publish: TopicPublishCommand = TopicPublishCommand()
