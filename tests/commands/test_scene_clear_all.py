"""Direct tests for :class:`SceneClearAllCommand` -- Humble Object testing (PL-TT-5)."""

from __future__ import annotations

import asyncio

from punt_lux.commands import Ctx, SceneOps, scene_clear_all
from punt_lux.domain.ids import ConnectionId
from punt_lux.operations import Cleared, OpError, Scope
from tests.commands._scene_stub import StubSceneOps, identity

_SCOPE = Scope(ConnectionId("test-conn"))


def test_clear_all_always_renders_cleared() -> None:
    ops = StubSceneOps(clear=Cleared())
    ctx: Ctx[SceneOps] = Ctx(ops=ops, identity=identity())

    result = asyncio.run(scene_clear_all(ctx, scope=_SCOPE))

    assert result.text == "cleared"
    assert result.error is False


def test_clear_all_renders_cleared_even_on_an_op_error() -> None:
    """Preserves the shipped tool's exact behavior: the outcome is discarded."""
    ops = StubSceneOps(clear=OpError(code="fault", reason="unreachable"))
    ctx: Ctx[SceneOps] = Ctx(ops=ops, identity=identity())

    result = asyncio.run(scene_clear_all(ctx, scope=_SCOPE))

    assert result.text == "cleared"
    assert result.error is False


def test_execute_returns_the_typed_outcome_with_no_envelope() -> None:
    ops = StubSceneOps(clear=Cleared())
    ctx: Ctx[SceneOps] = Ctx(ops=ops, identity=identity())

    result = asyncio.run(scene_clear_all.execute(ctx, scope=_SCOPE))

    assert result == Cleared()
