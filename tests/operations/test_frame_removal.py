"""FrameRemover against a real HubDisplay and a recording replicator."""

from __future__ import annotations

from punt_lux.domain.hub.connection_scoped_id import ConnectionScopedId
from punt_lux.domain.hub.hub import Hub
from punt_lux.domain.hub.hub_display import HubDisplay
from punt_lux.domain.hub.hub_factory import hub_element_factory
from punt_lux.domain.id_separator import ID_SEPARATOR
from punt_lux.domain.ids import ConnectionId, SceneId
from punt_lux.operations import Ok, OpError, RenderRequest, Scope
from punt_lux.operations.facade import Operations
from punt_lux.operations.frame_removal import FrameRemover
from punt_lux.operations.scene_deps import SceneOperationsDeps
from punt_lux.operations.scenes import SceneOperations

_CONNECTION = ConnectionId("local")
_LOCAL = Scope(_CONNECTION)


def _scoped(connection: ConnectionId, local_id: str) -> SceneId:
    """The store key ``local_id`` composes to for ``connection``."""
    return SceneId(ConnectionScopedId.compose(connection, local_id))


class _Recorder:
    """Records the replicator signals an operation sends."""

    def __init__(self) -> None:
        self.dirtied: list[SceneId] = []

    def mark_dirty(self, scene_id: SceneId) -> None:
        self.dirtied.append(scene_id)

    def mark_menus(self) -> None:
        """Unused here — removing a frame's content never marks the menu bar."""


def _show_framed(
    store: HubDisplay, recorder: _Recorder, connection: ConnectionId, frame_id: str
) -> None:
    """Show one scene for ``connection``, framed under ``frame_id``, via render()."""
    deps = SceneOperationsDeps(store, recorder, hub_element_factory, Hub())
    request = RenderRequest.parse(
        {
            "scene_id": "s1",
            "elements": [{"kind": "text", "id": "t1", "content": "Hi"}],
            "frame": {"frame_id": frame_id},
        }
    )
    SceneOperations(deps).render(request, scope=Scope(connection))


def test_remove_of_a_nonexistent_frame_is_not_found() -> None:
    # A frame never shown by anyone reports why, rather than a blanket
    # "removed" that tore nothing down (lux-03k6).
    store, recorder = HubDisplay(), _Recorder()
    result = FrameRemover(store, recorder).remove("ghost", _CONNECTION)
    assert isinstance(result, OpError)
    assert result.code == "not_found"
    assert recorder.dirtied == []


def test_remove_of_another_connections_frame_is_not_found() -> None:
    # A frame removed under the caller's OWN local name never resolves to a
    # different connection's frame -- DES-086 composition makes that
    # collision unrepresentable, so this is indistinguishable from "does not
    # exist" and reports the identical not_found. The other owner's scene is
    # left standing.
    store, recorder = HubDisplay(), _Recorder()
    stranger = ConnectionId("agent-b")
    _show_framed(store, recorder, stranger, "board")
    recorder.dirtied.clear()  # isolate remove()'s own dirty marks

    result = FrameRemover(store, recorder).remove("board", _CONNECTION)

    assert isinstance(result, OpError)
    assert result.code == "not_found"
    assert recorder.dirtied == []
    assert store.scene_roots(_scoped(stranger, "s1")) != []


def test_remove_of_a_blank_local_id_is_invalid_request() -> None:
    # ConnectionScopedId.compose raises ValueError for a blank local id;
    # FrameRemover maps it to a typed refusal rather than an unhandled fault.
    store, recorder = HubDisplay(), _Recorder()
    result = FrameRemover(store, recorder).remove("   ", _CONNECTION)
    assert isinstance(result, OpError)
    assert result.code == "invalid_request"
    assert recorder.dirtied == []


def test_remove_of_a_local_id_carrying_the_separator_is_invalid_request() -> None:
    # ConnectionScopedId.compose also raises for a local id carrying the unit
    # separator -- the same boundary condition, same typed refusal.
    store, recorder = HubDisplay(), _Recorder()
    result = FrameRemover(store, recorder).remove(f"a{ID_SEPARATOR}b", _CONNECTION)
    assert isinstance(result, OpError)
    assert result.code == "invalid_request"
    assert recorder.dirtied == []


def test_remove_removes_the_callers_own_frame_and_marks_dirty() -> None:
    store, recorder = HubDisplay(), _Recorder()
    _show_framed(store, recorder, _CONNECTION, "board")
    recorder.dirtied.clear()  # isolate remove()'s own dirty marks

    result = FrameRemover(store, recorder).remove("board", _CONNECTION)

    assert isinstance(result, Ok)
    assert store.scene_roots(_scoped(_CONNECTION, "s1")) == []
    assert recorder.dirtied == [_scoped(_CONNECTION, "s1")]


def test_close_frame_no_longer_exists_on_operations() -> None:
    """Rename train (lux-81t3.6): no alias survives for the retired op name."""
    assert not hasattr(Operations, "close_frame")
    assert not hasattr(FrameRemover, "close")
    assert hasattr(Operations, "remove_frame")
