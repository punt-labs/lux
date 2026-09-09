"""FrameCloser against a real HubDisplay and a recording replicator."""

from __future__ import annotations

from punt_lux.domain.hub.connection_scoped_id import ConnectionScopedId
from punt_lux.domain.hub.hub import Hub
from punt_lux.domain.hub.hub_display import HubDisplay
from punt_lux.domain.hub.hub_factory import hub_element_factory
from punt_lux.domain.ids import ConnectionId, SceneId
from punt_lux.operations import Ok, OpError, RenderRequest, Scope
from punt_lux.operations.frame_closing import FrameCloser
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
        """Unused here — closing a frame never marks the menu bar."""


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


def test_close_of_a_nonexistent_frame_is_not_found() -> None:
    # A frame never shown by anyone reports why, rather than a blanket
    # "closed" that tore nothing down (lux-03k6).
    store, recorder = HubDisplay(), _Recorder()
    result = FrameCloser(store, recorder).close("ghost", _CONNECTION)
    assert isinstance(result, OpError)
    assert result.code == "not_found"
    assert recorder.dirtied == []


def test_close_of_another_connections_frame_is_not_found() -> None:
    # A frame closed under the caller's OWN local name never resolves to a
    # different connection's frame -- DES-086 composition makes that
    # collision unrepresentable, so this is indistinguishable from "does not
    # exist" and reports the identical not_found. The other owner's scene is
    # left standing.
    store, recorder = HubDisplay(), _Recorder()
    stranger = ConnectionId("agent-b")
    _show_framed(store, recorder, stranger, "board")
    recorder.dirtied.clear()  # isolate close()'s own dirty marks

    result = FrameCloser(store, recorder).close("board", _CONNECTION)

    assert isinstance(result, OpError)
    assert result.code == "not_found"
    assert recorder.dirtied == []
    assert store.scene_roots(_scoped(stranger, "s1")) != []


def test_close_removes_the_callers_own_frame_and_marks_dirty() -> None:
    store, recorder = HubDisplay(), _Recorder()
    _show_framed(store, recorder, _CONNECTION, "board")
    recorder.dirtied.clear()  # isolate close()'s own dirty marks

    result = FrameCloser(store, recorder).close("board", _CONNECTION)

    assert isinstance(result, Ok)
    assert store.scene_roots(_scoped(_CONNECTION, "s1")) == []
    assert recorder.dirtied == [_scoped(_CONNECTION, "s1")]
