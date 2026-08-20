"""Direct tests for :class:`SceneDashboardCommand` -- Humble Object testing."""

from __future__ import annotations

import asyncio

from punt_lux.commands import Ctx, SceneOps, scene_dashboard
from punt_lux.domain.ids import ConnectionId
from punt_lux.operations import OpError, RenderDashboardRequest, SceneShown, Scope
from tests.commands._scene_stub import StubSceneOps, identity

_SCOPE = Scope(ConnectionId("test-conn"))
_REQUEST = RenderDashboardRequest.parse({"scene_id": "s1"})


def test_dashboard_success_renders_shipped_shown_line() -> None:
    ops = StubSceneOps(show=SceneShown(scene_id="s1"))
    ctx: Ctx[SceneOps] = Ctx(ops=ops, identity=identity())

    result = asyncio.run(scene_dashboard(ctx, _REQUEST, scope=_SCOPE))

    assert result.text == "shown:s1"
    assert result.error is False


def test_dashboard_rejection_shares_scene_show_rendering() -> None:
    ops = StubSceneOps(show=OpError(code="rejected", reason="bad chart"))
    ctx: Ctx[SceneOps] = Ctx(ops=ops, identity=identity())

    result = asyncio.run(scene_dashboard(ctx, _REQUEST, scope=_SCOPE))

    assert result.text == "error: scene not rendered — bad chart"
    assert result.error is True


def test_execute_returns_the_typed_outcome_with_no_envelope() -> None:
    ops = StubSceneOps(show=SceneShown(scene_id="s1"))
    ctx: Ctx[SceneOps] = Ctx(ops=ops, identity=identity())

    result = asyncio.run(scene_dashboard.execute(ctx, _REQUEST, scope=_SCOPE))

    assert result == SceneShown(scene_id="s1")


def test_routes_request_and_scope_through_to_ops() -> None:
    ops = StubSceneOps(show=SceneShown(scene_id="s1"))
    ctx: Ctx[SceneOps] = Ctx(ops=ops, identity=identity())

    asyncio.run(scene_dashboard.execute(ctx, _REQUEST, scope=_SCOPE))

    assert ops.last_call == {
        "method": "render_dashboard",
        "request": _REQUEST,
        "scope": _SCOPE,
    }
