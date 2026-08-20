"""Direct tests for :class:`SceneLsCommand` -- Humble Object testing (PL-TT-5)."""

from __future__ import annotations

import asyncio

from punt_lux.commands import Ctx, SceneOps, scene_ls
from punt_lux.operations import SceneList
from tests.commands._scene_stub import StubSceneOps, identity


def test_execute_returns_the_typed_outcome_with_no_envelope() -> None:
    scenes = SceneList(scenes=[], frames=[])
    ops = StubSceneOps(scenes=scenes)
    ctx: Ctx[SceneOps] = Ctx(ops=ops, identity=identity())

    result = asyncio.run(scene_ls.execute(ctx))

    assert result == scenes


def test_call_renders_the_scene_count_into_the_shared_envelope() -> None:
    scenes = SceneList(scenes=[], frames=[])
    ops = StubSceneOps(scenes=scenes)
    ctx: Ctx[SceneOps] = Ctx(ops=ops, identity=identity())

    result = asyncio.run(scene_ls(ctx))

    assert result.text == "scenes:0"
    assert result.error is False


def test_routes_the_zero_arg_call_through_to_list_scenes() -> None:
    ops = StubSceneOps(scenes=SceneList(scenes=[], frames=[]))
    ctx: Ctx[SceneOps] = Ctx(ops=ops, identity=identity())

    asyncio.run(scene_ls.execute(ctx))

    assert ops.last_call == {"method": "list_scenes"}
