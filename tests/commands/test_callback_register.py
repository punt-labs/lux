"""Direct tests for :class:`CallbackRegisterCommand` (PL-TT-5)."""

from __future__ import annotations

import asyncio

from punt_lux.commands import CallbackRegisterOps, Ctx, callback_register
from punt_lux.domain.ids import ConnectionId
from punt_lux.operations import Ok, OpError, Scope
from punt_lux.operations.models.callback_fields import CallbackFields
from punt_lux.operations.models.callbacks import RegisterCallbackRequest
from tests.commands._family_stubs import StubCallbackOps
from tests.commands._scene_stub import identity

_SCOPE = Scope(ConnectionId("test-conn"))


def _request() -> RegisterCallbackRequest | OpError:
    return RegisterCallbackRequest.parse(CallbackFields("cb1", "Open Ticket"))


def test_success_renders_registered_with_callers_id() -> None:
    ops = StubCallbackOps(register_result=Ok())
    ctx: Ctx[CallbackRegisterOps] = Ctx(ops=ops, identity=identity())

    result = asyncio.run(callback_register(ctx, _request(), scope=_SCOPE))

    assert result.text == "registered:cb1"
    assert result.error is False


def test_push_required_renders_shipped_error_line() -> None:
    ops = StubCallbackOps(
        register_result=OpError(code="push_required", reason="no listen leg")
    )
    ctx: Ctx[CallbackRegisterOps] = Ctx(ops=ops, identity=identity())

    result = asyncio.run(callback_register(ctx, _request(), scope=_SCOPE))

    assert result.text == "error: no listen leg"
    assert result.error is True


def test_routes_request_and_scope_through_to_ops() -> None:
    request = _request()
    ops = StubCallbackOps(register_result=Ok())
    ctx: Ctx[CallbackRegisterOps] = Ctx(ops=ops, identity=identity())

    asyncio.run(callback_register(ctx, request, scope=_SCOPE))

    assert ops.last_call == {
        "method": "register_callback",
        "request": request,
        "scope": _SCOPE,
    }
