"""Direct tests for :class:`EventLsCommand` (PL-TT-5)."""

from __future__ import annotations

import asyncio

from punt_lux.commands import Ctx, EventOps, event_ls
from punt_lux.operations import OpError
from punt_lux.operations.models.query_events import RecentEvents
from tests.commands._family_stubs import StubEventOps
from tests.commands._scene_stub import identity


def test_success_renders_event_count() -> None:
    ops = StubEventOps(result=RecentEvents(events=[], total_buffered=0))
    ctx: Ctx[EventOps] = Ctx(ops=ops, identity=identity())

    result = asyncio.run(event_ls(ctx, 50))

    assert result.text == "events:0"
    assert result.error is False


def test_display_unavailable_renders_shared_fault_line() -> None:
    ops = StubEventOps(result=OpError(code="display_unavailable", reason="down"))
    ctx: Ctx[EventOps] = Ctx(ops=ops, identity=identity())

    result = asyncio.run(event_ls(ctx, 50))

    assert result.text == "not running"
    assert result.error is True


def test_routes_count_through_to_ops() -> None:
    ops = StubEventOps(result=RecentEvents(events=[], total_buffered=0))
    ctx: Ctx[EventOps] = Ctx(ops=ops, identity=identity())

    asyncio.run(event_ls.execute(ctx, 42))

    assert ops.last_call == {"method": "list_recent_events", "count": 42}
