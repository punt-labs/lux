"""disconnect_connection cascades a drop into per-scene dirty marks.

When a connection drops, the store tears down its roots and returns every scene
it touched; the lifecycle entry point must then mark each of those scenes dirty
so the replicator blanks the ones the drop emptied and repaints the ones a
survivor still holds. This wires the real store to a recording replicator and
asserts the mark fires once per touched scene.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

import pytest

from punt_lux.domain.hub.hub import Hub
from punt_lux.domain.hub.hub_display import HubDisplay
from punt_lux.domain.hub.lifecycle import disconnect_connection
from punt_lux.domain.ids import ConnectionId, SceneId
from punt_lux.protocol.elements.text import TextElement

if TYPE_CHECKING:
    from collections.abc import Iterator

_CONN = ConnectionId("c1")


class _RecordingReplicator:
    """Records the scenes the disconnect cascade marks dirty."""

    marked: list[SceneId]
    __slots__ = ("marked",)

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self.marked = []
        return self

    def mark_dirty(self, scene_id: SceneId) -> None:
        self.marked.append(scene_id)


@pytest.fixture
def replicator(monkeypatch: pytest.MonkeyPatch) -> Iterator[_RecordingReplicator]:
    """Swap the module-level replicator the lifecycle marks through."""
    recorder = _RecordingReplicator()
    monkeypatch.setattr("punt_lux.domain.hub.lifecycle.hub_replicator", recorder)
    yield recorder


def test_disconnect_marks_each_scene_the_drop_touched_dirty(
    replicator: _RecordingReplicator,
) -> None:
    store = HubDisplay()
    store.register_client(_CONN)
    store.replace_scene(_CONN, SceneId("s1"), [TextElement(id="s1-root", content="x")])
    store.replace_scene(_CONN, SceneId("s2"), [TextElement(id="s2-root", content="y")])

    released: list[ConnectionId] = []
    disconnect_connection(_CONN, released.append, hub_display=store, hub=Hub())

    assert set(replicator.marked) == {SceneId("s1"), SceneId("s2")}
    assert released == [_CONN]  # the transport sink still fires after the cascade


def test_disconnect_of_an_unknown_connection_marks_nothing(
    replicator: _RecordingReplicator,
) -> None:
    # A connection that owns no scenes touches nothing, so no dirty mark fires —
    # but the transport sink still runs so per-session resources are released.
    store = HubDisplay()
    released: list[ConnectionId] = []
    disconnect_connection(_CONN, released.append, hub_display=store, hub=Hub())

    assert replicator.marked == []
    assert released == [_CONN]
