"""Direct tests for :class:`CallbackPendingCommand` (PL-TT-5)."""

from __future__ import annotations

import asyncio

from punt_lux.commands import CallbackOps, Ctx, callback_pending
from punt_lux.domain.hub.session_callback import CallbackInvocation
from punt_lux.domain.ids import ConnectionId
from punt_lux.operations import Scope
from tests.commands._family_stubs import StubCallbackOps
from tests.commands._scene_stub import identity

_SCOPE = Scope(ConnectionId("test-conn"))


def test_empty_pending_renders_zero_count() -> None:
    ops = StubCallbackOps(pending=())
    ctx: Ctx[CallbackOps] = Ctx(ops=ops, identity=identity())

    result = asyncio.run(callback_pending(ctx, scope=_SCOPE))

    assert result.text == "pending:0"
    assert result.json_data == {"pending": []}


def test_pending_invocations_render_into_the_json_payload() -> None:
    invocation = CallbackInvocation(ConnectionId("cx"), "cb1")
    ops = StubCallbackOps(pending=(invocation,))
    ctx: Ctx[CallbackOps] = Ctx(ops=ops, identity=identity())

    result = asyncio.run(callback_pending(ctx, scope=_SCOPE))

    assert result.text == "pending:1"
    assert result.json_data == {
        "pending": [{"connection_id": "cx", "callback_id": "cb1"}]
    }


def test_execute_returns_the_typed_tuple_with_no_envelope() -> None:
    invocation = CallbackInvocation(ConnectionId("cx"), "cb1")
    ops = StubCallbackOps(pending=(invocation,))
    ctx: Ctx[CallbackOps] = Ctx(ops=ops, identity=identity())

    result = asyncio.run(callback_pending.execute(ctx, scope=_SCOPE))

    assert result == (invocation,)
