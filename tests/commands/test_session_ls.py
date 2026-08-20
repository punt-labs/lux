"""Direct tests for :class:`SessionLsCommand` (PL-TT-5)."""

from __future__ import annotations

import asyncio

from punt_lux.commands import Ctx, SessionOps, session_ls
from punt_lux.operations import ClientList, OpError
from tests.commands._family_stubs import StubSessionOps
from tests.commands._scene_stub import identity


def test_execute_returns_the_typed_outcome_with_no_envelope() -> None:
    clients = ClientList(clients=[])
    ops = StubSessionOps(list_result=clients)
    ctx: Ctx[SessionOps] = Ctx(ops=ops, identity=identity())

    result = asyncio.run(session_ls.execute(ctx))

    assert result == clients


def test_call_renders_session_count_into_the_shared_envelope() -> None:
    ops = StubSessionOps(list_result=ClientList(clients=[]))
    ctx: Ctx[SessionOps] = Ctx(ops=ops, identity=identity())

    result = asyncio.run(session_ls(ctx))

    assert result.text == "sessions:0"
    assert result.error is False


def test_routes_the_zero_arg_call_through_to_list_clients() -> None:
    ops = StubSessionOps(list_result=ClientList(clients=[]))
    ctx: Ctx[SessionOps] = Ctx(ops=ops, identity=identity())

    asyncio.run(session_ls.execute(ctx))

    assert ops.last_call == {"method": "list_clients"}


def test_op_error_renders_the_shared_envelope_not_a_crash() -> None:
    """Regression: a REST-transport fault used to crash (RuntimeError) instead
    of reaching the shared error envelope."""
    ops = StubSessionOps(list_result=OpError(code="invalid_request", reason="bad"))
    ctx: Ctx[SessionOps] = Ctx(ops=ops, identity=identity())

    result = asyncio.run(session_ls(ctx))

    assert result.text == "error: bad"
    assert result.error is True
    assert result.exit_code == 1
