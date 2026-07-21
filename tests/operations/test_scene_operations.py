"""SceneOperations against a real HubDisplay, factory, and recording replicator."""

from __future__ import annotations

from punt_lux.domain.hub.hub_display import HubDisplay
from punt_lux.domain.ids import ConnectionId, ElementId, SceneId
from punt_lux.operations import OpError, RenderRequest, SceneShown, UpdateRequest
from punt_lux.operations.scenes import SceneOperations
from punt_lux.operations.scope import Scope
from punt_lux.protocol import CollapsingHeaderElement
from punt_lux.tools.hub_factory import hub_element_factory

_LOCAL = Scope(ConnectionId("local"))


class _Recorder:
    """Records the replicator signals an operation sends."""

    def __init__(self) -> None:
        self.dirtied: list[SceneId] = []
        self.cleared = 0

    def mark_dirty(self, scene_id: SceneId) -> None:
        self.dirtied.append(scene_id)

    def mark_cleared(self) -> None:
        self.cleared += 1


def _ops(store: HubDisplay, recorder: _Recorder) -> SceneOperations:
    return SceneOperations(store, recorder, hub_element_factory)


def _seed_header(store: HubDisplay, *, is_open: bool = False) -> None:
    store.replace_scene(
        ConnectionId("local"),
        SceneId("s1"),
        [CollapsingHeaderElement(id="hdr", label="Details", open=is_open)],
    )


def test_render_installs_scene_and_marks_dirty() -> None:
    store, recorder = HubDisplay(), _Recorder()
    request = RenderRequest.parse(
        {"scene_id": "s1", "elements": [{"kind": "text", "id": "t1", "content": "Hi"}]}
    )
    result = _ops(store, recorder).render(request, scope=_LOCAL)
    assert isinstance(result, SceneShown)
    assert result.scene_id == "s1"
    assert recorder.dirtied == [SceneId("s1")]
    assert store.resolve(SceneId("s1"), ElementId("t1")).id == "t1"


def test_render_passes_an_op_error_straight_through() -> None:
    recorder = _Recorder()
    error = OpError(code="invalid_request", reason="bad layout")
    result = _ops(HubDisplay(), recorder).render(error, scope=_LOCAL)
    assert result is error
    assert recorder.dirtied == []


def test_render_rejects_a_duplicate_id_and_installs_nothing() -> None:
    store, recorder = HubDisplay(), _Recorder()
    request = RenderRequest.parse(
        {
            "scene_id": "s1",
            "elements": [
                {"kind": "text", "id": "dup", "content": "a"},
                {"kind": "text", "id": "dup", "content": "b"},
            ],
        }
    )
    result = _ops(store, recorder).render(request, scope=_LOCAL)
    assert isinstance(result, OpError)
    assert result.code == "rejected"
    # The reason is bare — no "scene not rendered — " prefix; that is the adapter's.
    assert "duplicate" in result.reason
    assert recorder.dirtied == []


def test_render_rejects_an_undecodable_element_without_raising() -> None:
    store, recorder = HubDisplay(), _Recorder()
    request = RenderRequest.parse(
        {"scene_id": "s1", "elements": [{"kind": "text", "id": "t1"}]}
    )
    result = _ops(store, recorder).render(request, scope=_LOCAL)
    assert isinstance(result, OpError)
    assert result.code == "rejected"
    assert recorder.dirtied == []


def test_update_sets_a_field_and_marks_dirty() -> None:
    store, recorder = HubDisplay(), _Recorder()
    _seed_header(store, is_open=False)
    request = UpdateRequest.parse([{"id": "hdr", "set": {"open": True}}])
    result = _ops(store, recorder).update("s1", request, scope=_LOCAL)
    assert isinstance(result, SceneShown)
    header = store.resolve(SceneId("s1"), ElementId("hdr"))
    assert isinstance(header, CollapsingHeaderElement)
    assert header.open is True
    assert recorder.dirtied == [SceneId("s1")]


def test_update_rejects_an_unknown_element_and_leaves_the_store_untouched() -> None:
    store, recorder = HubDisplay(), _Recorder()
    _seed_header(store)
    request = UpdateRequest.parse([{"id": "ghost", "set": {"open": True}}])
    result = _ops(store, recorder).update("s1", request, scope=_LOCAL)
    assert isinstance(result, OpError)
    assert result.code == "rejected"
    # The reason is bare — the writer names the element; the adapter adds the prefix.
    assert "ghost" in result.reason
    assert recorder.dirtied == []
    assert store.resolve(SceneId("s1"), ElementId("hdr")).id == "hdr"


def test_clear_empties_the_scene_and_marks_cleared() -> None:
    store, recorder = HubDisplay(), _Recorder()
    _seed_header(store)
    _ops(store, recorder).clear(scope=_LOCAL)
    assert store.scene_roots(SceneId("s1")) == []
    assert recorder.cleared == 1
