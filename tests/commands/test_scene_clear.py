"""Direct tests for :class:`SceneClearCommand` -- Humble Object testing (PL-TT-5)."""

from __future__ import annotations

import asyncio

from punt_lux.commands import Ctx, SceneOps, scene_clear
from punt_lux.domain.ids import ConnectionId
from punt_lux.operations import Cleared, OpError, Scope
from tests.commands._scene_stub import StubSceneOps, identity

_SCOPE = Scope(ConnectionId("test-conn"))


def test_clear_success_renders_cleared() -> None:
    ops = StubSceneOps(clear=Cleared())
    ctx: Ctx[SceneOps] = Ctx(ops=ops, identity=identity())

    result = asyncio.run(scene_clear(ctx, "s1", scope=_SCOPE))

    assert result.text == "cleared"
    assert result.error is False


def test_clear_unknown_scene_renders_shared_fault_line() -> None:
    """An unmistyped id never looks like a successful clear."""
    ops = StubSceneOps(clear=OpError(code="not_found", reason="scene 's1' not found"))
    ctx: Ctx[SceneOps] = Ctx(ops=ops, identity=identity())

    result = asyncio.run(scene_clear(ctx, "s1", scope=_SCOPE))

    assert result.text == "error: scene 's1' not found"
    assert result.error is True
    assert result.exit_code == 1


def test_execute_returns_the_typed_outcome_with_no_envelope() -> None:
    ops = StubSceneOps(clear=Cleared())
    ctx: Ctx[SceneOps] = Ctx(ops=ops, identity=identity())

    result = asyncio.run(scene_clear.execute(ctx, "s1", scope=_SCOPE))

    assert result == Cleared()
