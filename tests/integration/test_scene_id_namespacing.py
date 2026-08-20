"""DES-086 regression: two connections' identical raw scene_id never collide.

The reported bug, closed end to end: vox pushed ``scene_id="music-player"``
from two Claude Code sessions at once, and the second silently evicted the
first because the Hub stored every scene under the literal string a client
submitted, with no ownership check on the first write to a given id.

These tests drive the real ``SceneOperations``/``QueryOperations`` — the
production write and read paths, nothing stubbed but the process boundary —
against one shared ``HubDisplay``, the way two independent connections would
share one Hub. Each proves one property DES-086 promises: coexistence,
idempotent re-show, connection-scoped update, and connection-scoped clear.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from punt_lux.domain.hub.hub import Hub
from punt_lux.domain.hub.hub_display import HubDisplay
from punt_lux.domain.hub.hub_factory import hub_element_factory
from punt_lux.domain.ids import ConnectionId, ElementId, SceneId
from punt_lux.operations import (
    Cleared,
    OpError,
    RenderRequest,
    SceneShown,
    UpdateRequest,
)
from punt_lux.operations.queries import QueryOperations
from punt_lux.operations.scenes import SceneOperations
from punt_lux.operations.scope import Scope
from punt_lux.protocol import TextElement

if TYPE_CHECKING:
    from collections.abc import Mapping

    from punt_lux.operations.display_reply import DisplayReply

pytestmark = pytest.mark.integration

_A = ConnectionId("session-a")
_B = ConnectionId("session-b")
_SCOPE_A = Scope(_A)
_SCOPE_B = Scope(_B)
_MUSIC_PLAYER = "music-player"


class _Recorder:
    """Records the replicator signals an operation sends — unused here."""

    def mark_dirty(self, scene_id: SceneId) -> None:
        """Ignore the dirty mark — these tests read the store directly."""

    def mark_menus(self) -> None:
        """Ignore the menu mark — unused here."""


class _ForbiddenPort:
    """A DisplayPort that fails the test if any proxied call is made."""

    def query(self, method: str, params: Mapping[str, object]) -> DisplayReply:
        msg = f"unexpected display proxy: query({method!r})"
        raise AssertionError(msg)

    def ping(self, wait: float | None) -> DisplayReply:
        msg = f"unexpected display proxy: ping({wait!r})"
        raise AssertionError(msg)


def _stack() -> tuple[HubDisplay, SceneOperations, QueryOperations]:
    """One shared store, two independent connections' worth of operations."""
    store = HubDisplay()
    hub = Hub()
    scenes = SceneOperations(store, _Recorder(), hub_element_factory, hub)
    queries = QueryOperations(store, hub, _ForbiddenPort())
    return store, scenes, queries


def _render(scenes: SceneOperations, scope: Scope, scene_id: str) -> SceneShown:
    request = RenderRequest.parse(
        {
            "scene_id": scene_id,
            "elements": [
                {"kind": "text", "id": "widget", "content": str(scope.connection_id)}
            ],
        }
    )
    result = scenes.render(request, scope=scope)
    assert isinstance(result, SceneShown)
    return result


def test_two_connections_coexist_under_the_identical_raw_scene_id() -> None:
    """Two sessions each show("music-player"); both scenes coexist, distinctly owned."""
    _store, scenes, queries = _stack()

    _render(scenes, _SCOPE_A, _MUSIC_PLAYER)
    _render(scenes, _SCOPE_B, _MUSIC_PLAYER)

    scene_list = queries.list_scenes()
    music_player_scenes = [s for s in scene_list.scenes if s.local_id == _MUSIC_PLAYER]
    assert len(music_player_scenes) == 2  # neither evicted the other

    owning_connections = {
        s.owners[0].connection_id for s in music_player_scenes if s.owners
    }
    assert owning_connections == {str(_A), str(_B)}

    # Both carry the identical local_id — what each caller called it — while
    # their composed scene_id (the actual store key) differs.
    assert {s.local_id for s in music_player_scenes} == {_MUSIC_PLAYER}
    composed_keys = {s.scene_id for s in music_player_scenes}
    assert len(composed_keys) == 2


def test_a_single_connections_re_show_is_idempotent() -> None:
    """The same connection showing the same raw id twice updates one scene."""
    store, scenes, queries = _stack()

    first = _render(scenes, _SCOPE_A, _MUSIC_PLAYER)
    second_request = RenderRequest.parse(
        {
            "scene_id": _MUSIC_PLAYER,
            "elements": [{"kind": "text", "id": "widget", "content": "second-payload"}],
        }
    )
    second = scenes.render(second_request, scope=_SCOPE_A)
    assert isinstance(second, SceneShown)

    assert first.scene_id == second.scene_id == _MUSIC_PLAYER  # caller's own name
    scene_list = queries.list_scenes()
    music_player_scenes = [s for s in scene_list.scenes if s.local_id == _MUSIC_PLAYER]
    assert len(music_player_scenes) == 1  # the second show updated, not created

    # The second payload actually reached the store — a no-op replace_scene
    # on a matching key would still leave the count at 1 but the content stale.
    sid = SceneId(music_player_scenes[0].scene_id)
    widget = store.resolve(sid, ElementId("widget"))
    assert isinstance(widget, TextElement)
    assert widget.content == "second-payload"


def test_two_connections_with_the_same_explicit_frame_id_do_not_share_a_frame() -> None:
    """Decision 2 (unconditional): an explicit frame_id is namespaced too."""
    _store, scenes, queries = _stack()

    request_a = RenderRequest.parse(
        {
            "scene_id": "panel-a",
            "elements": [{"kind": "text", "id": "widget", "content": str(_A)}],
            "frame": {"frame_id": "shared"},
        }
    )
    request_b = RenderRequest.parse(
        {
            "scene_id": "panel-b",
            "elements": [{"kind": "text", "id": "widget", "content": str(_B)}],
            "frame": {"frame_id": "shared"},
        }
    )
    result_a = scenes.render(request_a, scope=_SCOPE_A)
    result_b = scenes.render(request_b, scope=_SCOPE_B)
    assert isinstance(result_a, SceneShown)
    assert isinstance(result_b, SceneShown)

    panels = {"panel-a", "panel-b"}
    scene_list = queries.list_scenes()
    frame_ids = {s.frame_id for s in scene_list.scenes if s.local_id in panels}
    # Both callers asked for frame_id="shared"; composed against two different
    # connections, the store keys can never collide into one frame.
    assert len(frame_ids) == 2


def _owned_scene_id(queries: QueryOperations, owner: ConnectionId) -> SceneId:
    summary = next(
        s
        for s in queries.list_scenes().scenes
        if s.local_id == _MUSIC_PLAYER and s.owners[0].connection_id == str(owner)
    )
    return SceneId(summary.scene_id)


def test_update_from_one_connection_never_touches_the_others_scene() -> None:
    """A patches its own "music-player"; B's identically-named scene is untouched."""
    store, scenes, queries = _stack()

    _render(scenes, _SCOPE_A, _MUSIC_PLAYER)
    _render(scenes, _SCOPE_B, _MUSIC_PLAYER)

    patch = UpdateRequest.parse([{"id": "widget", "set": {"content": "patched-by-a"}}])
    result = scenes.update(_MUSIC_PLAYER, patch, scope=_SCOPE_A)
    assert isinstance(result, SceneShown)

    a_widget = store.resolve(_owned_scene_id(queries, _A), ElementId("widget"))
    b_widget = store.resolve(_owned_scene_id(queries, _B), ElementId("widget"))
    assert isinstance(a_widget, TextElement)
    assert isinstance(b_widget, TextElement)
    assert a_widget.content == "patched-by-a"
    assert b_widget.content == str(_B)  # B's scene, never touched


def test_clear_from_one_connection_never_touches_the_others_scene() -> None:
    """A clears its own "music-player"; B's identically-named scene survives."""
    _store, scenes, queries = _stack()

    _render(scenes, _SCOPE_A, _MUSIC_PLAYER)
    _render(scenes, _SCOPE_B, _MUSIC_PLAYER)

    result = scenes.clear(scope=_SCOPE_A, scene_id=_MUSIC_PLAYER)
    assert isinstance(result, Cleared)

    scene_list = queries.list_scenes()
    music_player_scenes = [s for s in scene_list.scenes if s.local_id == _MUSIC_PLAYER]
    assert len(music_player_scenes) == 1  # only A's was removed
    assert music_player_scenes[0].owners[0].connection_id == str(_B)

    # A's clear of its own scene reports success; a second clear finds nothing
    # left of A's to remove and is refused, never a false "cleared".
    second = scenes.clear(scope=_SCOPE_A, scene_id=_MUSIC_PLAYER)
    assert isinstance(second, OpError)
    assert second.code == "not_found"
