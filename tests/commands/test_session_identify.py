"""Direct tests for :class:`SessionIdentifyCommand` (PL-TT-5)."""

from __future__ import annotations

import asyncio

from punt_lux.commands import Ctx, SessionOps, session_identify
from punt_lux.domain.hub.client_identity import ClientIdentity
from punt_lux.domain.ids import ConnectionId
from punt_lux.operations import OpError, Scope
from punt_lux.operations.models.identity import Identified
from tests.commands._family_stubs import StubSessionOps
from tests.commands._scene_stub import identity

_SCOPE = Scope(ConnectionId("test-conn"))
_DECLARATION: dict[str, object] = {"kind": "cli", "name": "someone"}


def test_success_renders_identified_line() -> None:
    who = ClientIdentity(kind="cli", name="someone")
    ops = StubSessionOps(identify_result=Identified(identity=who))
    ctx: Ctx[SessionOps] = Ctx(ops=ops, identity=identity())

    result = asyncio.run(session_identify(ctx, _DECLARATION, scope=_SCOPE))

    assert result.text == "identified:someone"
    assert result.error is False


def test_routes_declaration_and_scope_through_to_ops() -> None:
    who = ClientIdentity(kind="cli", name="someone")
    ops = StubSessionOps(identify_result=Identified(identity=who))
    ctx: Ctx[SessionOps] = Ctx(ops=ops, identity=identity())

    asyncio.run(session_identify.execute(ctx, _DECLARATION, scope=_SCOPE))

    assert ops.last_call == {
        "method": "identify",
        "declaration": _DECLARATION,
        "scope": _SCOPE,
    }


def test_malformed_declaration_renders_shared_fault_line() -> None:
    ops = StubSessionOps(
        identify_result=OpError(code="invalid_request", reason="bad kind")
    )
    ctx: Ctx[SessionOps] = Ctx(ops=ops, identity=identity())

    result = asyncio.run(session_identify(ctx, _DECLARATION, scope=_SCOPE))

    assert result.text == "error: bad kind"
    assert result.error is True
