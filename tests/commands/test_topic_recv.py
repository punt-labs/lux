"""Direct tests for :class:`TopicRecvCommand` (PL-TT-5)."""

from __future__ import annotations

import asyncio

from punt_lux.commands import Ctx, TopicOps, topic_recv
from punt_lux.domain.ids import ConnectionId
from punt_lux.operations import Scope
from punt_lux.operations.models.pubsub import BusEvent, Received
from tests.commands._family_stubs import StubTopicOps
from tests.commands._scene_stub import identity

_SCOPE = Scope(ConnectionId("test-conn"))


def test_empty_inbox_renders_none() -> None:
    ops = StubTopicOps(receive=Received(event=None))
    ctx: Ctx[TopicOps] = Ctx(ops=ops, identity=identity())

    result = asyncio.run(topic_recv(ctx, scope=_SCOPE))

    assert result.text == "none"
    assert result.error is False


def test_business_event_renders_shipped_line() -> None:
    event = BusEvent(topic="openTicket", payload={"id": 42})
    ops = StubTopicOps(receive=Received(event=event))
    ctx: Ctx[TopicOps] = Ctx(ops=ops, identity=identity())

    result = asyncio.run(topic_recv(ctx, scope=_SCOPE))

    assert result.text == 'event:openTicket:{"id": 42}'
    assert result.error is False


def test_routes_scope_through_to_ops() -> None:
    ops = StubTopicOps(receive=Received(event=None))
    ctx: Ctx[TopicOps] = Ctx(ops=ops, identity=identity())

    asyncio.run(topic_recv.execute(ctx, scope=_SCOPE))

    assert ops.last_call == {"method": "receive", "scope": _SCOPE}
