"""Direct tests for :class:`TopicSubscribeCommand` (PL-TT-5)."""

from __future__ import annotations

import asyncio

from punt_lux.commands import Ctx, TopicOps, topic_subscribe
from punt_lux.domain.ids import ConnectionId
from punt_lux.operations import Scope
from punt_lux.operations.models.pubsub_acks import Subscribed
from tests.commands._family_stubs import StubTopicOps
from tests.commands._scene_stub import identity

_SCOPE = Scope(ConnectionId("test-conn"))


def test_success_renders_subscribed_line() -> None:
    ops = StubTopicOps(subscribe=Subscribed(topic="t1"))
    ctx: Ctx[TopicOps] = Ctx(ops=ops, identity=identity())

    result = asyncio.run(topic_subscribe(ctx, "t1", scope=_SCOPE))

    assert result.text == "subscribed:t1"
    assert result.error is False


def test_routes_topic_and_scope_through_to_ops() -> None:
    ops = StubTopicOps(subscribe=Subscribed(topic="t1"))
    ctx: Ctx[TopicOps] = Ctx(ops=ops, identity=identity())

    asyncio.run(topic_subscribe(ctx, "t1", scope=_SCOPE))

    assert ops.last_call == {
        "method": "subscribe",
        "topic": "t1",
        "scope": _SCOPE,
    }
