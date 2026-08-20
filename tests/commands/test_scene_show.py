"""Direct tests for :class:`SceneShowCommand` -- Humble Object testing (PL-TT-5)."""

from __future__ import annotations

import asyncio

from punt_lux.commands import Ctx, SceneOps, scene_show
from punt_lux.domain.ids import ConnectionId
from punt_lux.operations import OpError, RenderRequest, SceneShown, Scope
from tests.commands._scene_stub import StubSceneOps, identity

_SCOPE = Scope(ConnectionId("test-conn"))
_REQUEST = RenderRequest.parse({"scene_id": "s1", "elements": []})


def test_show_success_renders_shipped_shown_line() -> None:
    ops = StubSceneOps(show=SceneShown(scene_id="s1"))
    ctx: Ctx[SceneOps] = Ctx(ops=ops, identity=identity())

    result = asyncio.run(scene_show(ctx, _REQUEST, scope=_SCOPE))

    assert result.text == "shown:s1"
    assert result.json_data == {"scene_id": "s1"}
    assert result.error is False


def test_show_rejection_renders_prefixed_error_line() -> None:
    ops = StubSceneOps(show=OpError(code="rejected", reason="bad element"))
    ctx: Ctx[SceneOps] = Ctx(ops=ops, identity=identity())

    result = asyncio.run(scene_show(ctx, _REQUEST, scope=_SCOPE))

    assert result.text == "error: scene not rendered — bad element"
    assert result.error is True
    assert result.exit_code == 1


def test_show_invalid_request_renders_unprefixed_error_line() -> None:
    """A parse-level ``invalid_request`` keeps its own message, with no prefix."""
    ops = StubSceneOps(show=OpError(code="invalid_request", reason="malformed"))
    ctx: Ctx[SceneOps] = Ctx(ops=ops, identity=identity())

    result = asyncio.run(scene_show(ctx, _REQUEST, scope=_SCOPE))

    assert result.text == "error: malformed"


def test_execute_returns_the_typed_outcome_with_no_envelope() -> None:
    ops = StubSceneOps(show=SceneShown(scene_id="s1"))
    ctx: Ctx[SceneOps] = Ctx(ops=ops, identity=identity())

    result = asyncio.run(scene_show.execute(ctx, _REQUEST, scope=_SCOPE))

    assert result == SceneShown(scene_id="s1")


def test_routes_request_and_scope_through_to_ops() -> None:
    ops = StubSceneOps(show=SceneShown(scene_id="s1"))
    ctx: Ctx[SceneOps] = Ctx(ops=ops, identity=identity())

    asyncio.run(scene_show.execute(ctx, _REQUEST, scope=_SCOPE))

    assert ops.last_call == {
        "method": "render",
        "request": _REQUEST,
        "scope": _SCOPE,
    }
