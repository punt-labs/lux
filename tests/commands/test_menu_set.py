"""Direct tests for :class:`MenuSetCommand` (PL-TT-5)."""

from __future__ import annotations

import asyncio

from punt_lux.commands import Ctx, MenuOps, menu_set
from punt_lux.operations import Ok, OpError, SetMenuRequest
from tests.commands._family_stubs import StubMenuOps
from tests.commands._scene_stub import identity


def _request() -> SetMenuRequest | OpError:
    return SetMenuRequest.parse([])


def test_success_renders_ok() -> None:
    ops = StubMenuOps(set_result=Ok())
    ctx: Ctx[MenuOps] = Ctx(ops=ops, identity=identity())

    result = asyncio.run(menu_set(ctx, _request()))

    assert result.text == "ok"
    assert result.error is False


def test_fault_renders_shared_fault_line() -> None:
    ops = StubMenuOps(set_result=OpError(code="fault", reason="malformed reply"))
    ctx: Ctx[MenuOps] = Ctx(ops=ops, identity=identity())

    result = asyncio.run(menu_set(ctx, _request()))

    assert result.text == "error: malformed reply"
    assert result.error is True


def test_execute_returns_the_typed_outcome_with_no_envelope() -> None:
    ops = StubMenuOps(set_result=Ok())
    ctx: Ctx[MenuOps] = Ctx(ops=ops, identity=identity())

    result = asyncio.run(menu_set.execute(ctx, _request()))

    assert result == Ok()
