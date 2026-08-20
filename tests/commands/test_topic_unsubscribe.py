"""Direct tests for :class:`TopicUnsubscribeCommand` (PL-TT-5)."""

from __future__ import annotations

import asyncio

from punt_lux.commands import Ctx, TopicOps, topic_unsubscribe
from punt_lux.domain.ids import ConnectionId
from punt_lux.operations import Scope
from punt_lux.operations.models.pubsub_acks import Unsubscribed
from tests.commands._family_stubs import StubTopicOps
from tests.commands._scene_stub import identity

_SCOPE = Scope(ConnectionId("test-conn"))


def test_success_renders_unsubscribed_line() -> None:
    ops = StubTopicOps(unsubscribe=Unsubscribed(topic="t1"))
    ctx: Ctx[TopicOps] = Ctx(ops=ops, identity=identity())

    result = asyncio.run(topic_unsubscribe(ctx, "t1", scope=_SCOPE))

    assert result.text == "unsubscribed:t1"
    assert result.error is False
