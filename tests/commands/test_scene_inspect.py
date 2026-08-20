"""Direct tests for :class:`SceneInspectCommand` -- Humble Object testing (PL-TT-5)."""

from __future__ import annotations

import asyncio

from punt_lux.commands import Ctx, SceneOps, scene_inspect
from punt_lux.domain.ids import ConnectionId
from punt_lux.operations import OpError, SceneInspection, Scope
from punt_lux.operations.models.inspect_scope import HUB_ONLY
from tests.commands._scene_stub import StubSceneOps, identity

_SCOPE = Scope(ConnectionId("test-conn"))


def test_inspect_success_returns_typed_result_with_no_envelope() -> None:
    inspection = SceneInspection(scene_id="s1", elements=[])
    ops = StubSceneOps(inspect=inspection)
    ctx: Ctx[SceneOps] = Ctx(ops=ops, identity=identity())

    result = asyncio.run(scene_inspect.execute(ctx, "s1", scope=_SCOPE))

    assert result == inspection


def test_call_renders_success_into_the_shared_envelope() -> None:
    inspection = SceneInspection(scene_id="s1", elements=[])
    ops = StubSceneOps(inspect=inspection)
    ctx: Ctx[SceneOps] = Ctx(ops=ops, identity=identity())

    result = asyncio.run(scene_inspect(ctx, "s1", scope=_SCOPE))

    assert result.text == "scene:s1"
    assert result.error is False


def test_call_renders_unowned_scene_as_an_error() -> None:
    ops = StubSceneOps(inspect=OpError(code="not_found", reason="scene 's1' not found"))
    ctx: Ctx[SceneOps] = Ctx(ops=ops, identity=identity())

    result = asyncio.run(scene_inspect(ctx, "s1", scope=_SCOPE))

    assert result.text == "error: scene 's1' not found"
    assert result.error is True


def test_routes_scene_id_scope_and_default_facts_through_to_ops() -> None:
    inspection = SceneInspection(scene_id="s1", elements=[])
    ops = StubSceneOps(inspect=inspection)
    ctx: Ctx[SceneOps] = Ctx(ops=ops, identity=identity())

    asyncio.run(scene_inspect.execute(ctx, "s1", scope=_SCOPE))

    assert ops.last_call == {
        "method": "inspect_scene",
        "scene_id": "s1",
        "scope": _SCOPE,
        "facts": HUB_ONLY,
    }
