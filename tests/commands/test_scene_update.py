"""Direct tests for :class:`SceneUpdateCommand` -- Humble Object testing (PL-TT-5)."""

from __future__ import annotations

import asyncio

from punt_lux.commands import Ctx, SceneOps, scene_update
from punt_lux.domain.ids import ConnectionId
from punt_lux.operations import OpError, SceneShown, Scope, UpdateRequest
from tests.commands._scene_stub import StubSceneOps, identity

_SCOPE = Scope(ConnectionId("test-conn"))
_PATCHES = UpdateRequest.parse([{"id": "t1", "set": {"content": "hi"}}])


def test_update_success_renders_shipped_shown_line() -> None:
    ops = StubSceneOps(show=SceneShown(scene_id="s1"))
    ctx: Ctx[SceneOps] = Ctx(ops=ops, identity=identity())

    result = asyncio.run(scene_update(ctx, "s1", _PATCHES, scope=_SCOPE))

    assert result.text == "shown:s1"
    assert result.error is False


def test_update_rejection_renders_shipped_error_line() -> None:
    ops = StubSceneOps(show=OpError(code="rejected", reason="unknown field"))
    ctx: Ctx[SceneOps] = Ctx(ops=ops, identity=identity())

    result = asyncio.run(scene_update(ctx, "s1", _PATCHES, scope=_SCOPE))

    assert result.text == "error: scene not updated — unknown field"
    assert result.error is True
    assert result.exit_code == 1


def test_execute_returns_the_typed_outcome_with_no_envelope() -> None:
    ops = StubSceneOps(show=SceneShown(scene_id="s1"))
    ctx: Ctx[SceneOps] = Ctx(ops=ops, identity=identity())

    result = asyncio.run(scene_update.execute(ctx, "s1", _PATCHES, scope=_SCOPE))

    assert result == SceneShown(scene_id="s1")
