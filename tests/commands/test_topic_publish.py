"""Direct tests for :class:`TopicPublishCommand` (PL-TT-5)."""

from __future__ import annotations

import asyncio

from punt_lux.commands import Ctx, TopicOps, topic_publish
from punt_lux.domain.ids import ConnectionId
from punt_lux.operations import Scope
from punt_lux.operations.models.pubsub import PublishRequest
from punt_lux.operations.models.pubsub_acks import Published
from tests.commands._family_stubs import StubTopicOps
from tests.commands._scene_stub import identity

_SCOPE = Scope(ConnectionId("test-conn"))


def test_success_renders_delivered_count() -> None:
    ops = StubTopicOps(publish=Published(delivered=3))
    ctx: Ctx[TopicOps] = Ctx(ops=ops, identity=identity())
    request = PublishRequest(payload={"x": 1})

    result = asyncio.run(topic_publish(ctx, "t1", request, scope=_SCOPE))

    assert result.text == "delivered:3"
    assert result.error is False


def test_zero_subscribers_is_normal_success() -> None:
    ops = StubTopicOps(publish=Published(delivered=0))
    ctx: Ctx[TopicOps] = Ctx(ops=ops, identity=identity())

    result = asyncio.run(
        topic_publish(ctx, "t1", PublishRequest(payload={}), scope=_SCOPE)
    )

    assert result.text == "delivered:0"
    assert result.error is False


def test_routes_topic_request_and_scope_through_to_ops() -> None:
    ops = StubTopicOps(publish=Published(delivered=1))
    ctx: Ctx[TopicOps] = Ctx(ops=ops, identity=identity())
    req = PublishRequest(payload={"k": "v"})

    asyncio.run(topic_publish.execute(ctx, "t1", req, scope=_SCOPE))

    assert ops.last_call == {
        "method": "publish",
        "topic": "t1",
        "request": req,
        "scope": _SCOPE,
    }
