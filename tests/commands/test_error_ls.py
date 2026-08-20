"""Direct tests for :class:`ErrorLsCommand` (PL-TT-5)."""

from __future__ import annotations

import asyncio

from punt_lux.commands import Ctx, ErrorOps, error_ls
from punt_lux.operations import OpError
from punt_lux.operations.models.query_errors import RecentErrors
from tests.commands._family_stubs import StubErrorOps
from tests.commands._scene_stub import identity


def test_success_renders_error_count() -> None:
    ops = StubErrorOps(result=RecentErrors(errors=[], total_buffered=0))
    ctx: Ctx[ErrorOps] = Ctx(ops=ops, identity=identity())

    result = asyncio.run(error_ls(ctx, 20))

    assert result.text == "errors:0"
    assert result.error is False


def test_display_unavailable_renders_shared_fault_line() -> None:
    ops = StubErrorOps(result=OpError(code="display_unavailable", reason="down"))
    ctx: Ctx[ErrorOps] = Ctx(ops=ops, identity=identity())

    result = asyncio.run(error_ls(ctx, 20))

    assert result.text == "not running"
    assert result.error is True


def test_routes_count_through_to_ops() -> None:
    ops = StubErrorOps(result=RecentErrors(errors=[], total_buffered=0))
    ctx: Ctx[ErrorOps] = Ctx(ops=ops, identity=identity())

    asyncio.run(error_ls(ctx, 20))

    assert ops.last_call == {"method": "list_errors", "count": 20}
