"""Direct tests for :class:`SceneTableCommand` -- Humble Object testing (PL-TT-5)."""

from __future__ import annotations

import asyncio

from punt_lux.commands import Ctx, SceneOps, scene_table
from punt_lux.domain.ids import ConnectionId
from punt_lux.operations import OpError, RenderTableRequest, SceneShown, Scope
from tests.commands._scene_stub import StubSceneOps, identity

_SCOPE = Scope(ConnectionId("test-conn"))
_REQUEST = RenderTableRequest.parse(
    {"scene_id": "s1", "columns": ["a"], "rows": [["1"]]}
)


def test_table_success_renders_shipped_shown_line() -> None:
    ops = StubSceneOps(show=SceneShown(scene_id="s1"))
    ctx: Ctx[SceneOps] = Ctx(ops=ops, identity=identity())

    result = asyncio.run(scene_table(ctx, _REQUEST, scope=_SCOPE))

    assert result.text == "shown:s1"
    assert result.error is False


def test_table_rejection_shares_scene_show_rendering() -> None:
    """Table and dashboard share ``SceneShowCommand.render_outcome`` verbatim."""
    ops = StubSceneOps(show=OpError(code="rejected", reason="bad columns"))
    ctx: Ctx[SceneOps] = Ctx(ops=ops, identity=identity())

    result = asyncio.run(scene_table(ctx, _REQUEST, scope=_SCOPE))

    assert result.text == "error: scene not rendered — bad columns"
    assert result.error is True


def test_execute_returns_the_typed_outcome_with_no_envelope() -> None:
    ops = StubSceneOps(show=SceneShown(scene_id="s1"))
    ctx: Ctx[SceneOps] = Ctx(ops=ops, identity=identity())

    result = asyncio.run(scene_table.execute(ctx, _REQUEST, scope=_SCOPE))

    assert result == SceneShown(scene_id="s1")


def test_routes_request_and_scope_through_to_ops() -> None:
    ops = StubSceneOps(show=SceneShown(scene_id="s1"))
    ctx: Ctx[SceneOps] = Ctx(ops=ops, identity=identity())

    asyncio.run(scene_table.execute(ctx, _REQUEST, scope=_SCOPE))

    assert ops.last_call == {
        "method": "render_table",
        "request": _REQUEST,
        "scope": _SCOPE,
    }
