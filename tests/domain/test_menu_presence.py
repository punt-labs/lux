"""MenuPresence — a presence change pays a mark and binds the one shared sink."""

from __future__ import annotations

from typing import Self, final

from punt_lux.domain.hub.departure_sinks import DepartureSink
from punt_lux.domain.hub.menu_presence import MarkMenusSink, MenuPresence
from punt_lux.domain.ids import ConnectionId, SceneId

_CONN = ConnectionId("agent")


@final
class _Marker:
    """A DirtyMarker counting menu marks."""

    marks: int
    __slots__ = ("marks",)

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self.marks = 0
        return self

    def mark_dirty(self, scene_id: SceneId) -> None:
        raise AssertionError(f"menu presence must not mark scene {scene_id!r}")

    def mark_menus(self) -> None:
        self.marks += 1


@final
class _Binder:
    """A SinkBinder recording what was bound where."""

    bound: list[tuple[ConnectionId, DepartureSink]]
    __slots__ = ("bound",)

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self.bound = []
        return self

    def bind_sink(self, connection_id: ConnectionId, sink: DepartureSink) -> None:
        self.bound.append((connection_id, sink))


def _marking(marker: _Marker) -> MenuPresence:
    """Presence whose sink does nothing beyond marking ``marker``."""
    return MenuPresence(marker, MarkMenusSink(marker))


def test_an_unchanged_presence_pays_nothing() -> None:
    marker, binder = _Marker(), _Binder()

    _marking(marker).announce("unchanged", _CONN, binder)

    assert marker.marks == 0
    assert binder.bound == []


def test_a_gained_presence_marks_and_binds() -> None:
    marker, binder = _Marker(), _Binder()

    _marking(marker).announce("gained", _CONN, binder)

    assert marker.marks == 1
    assert [conn for conn, _ in binder.bound] == [_CONN]


def test_a_revised_presence_marks_and_binds() -> None:
    marker, binder = _Marker(), _Binder()

    _marking(marker).announce("revised", _CONN, binder)

    assert marker.marks == 1
    assert len(binder.bound) == 1


def test_every_announcement_binds_the_same_sink_object() -> None:
    binder = _Binder()
    presence = _marking(_Marker())

    presence.announce("gained", _CONN, binder)
    presence.announce("revised", ConnectionId("other"), binder)
    presence.arm(_CONN, binder)

    sinks = [sink for _, sink in binder.bound]
    assert all(sink is sinks[0] for sink in sinks)


def test_arming_binds_without_marking() -> None:
    marker, binder = _Marker(), _Binder()

    _marking(marker).arm(_CONN, binder)

    assert marker.marks == 0
    assert len(binder.bound) == 1


def test_the_marking_sink_marks_when_fired() -> None:
    marker = _Marker()

    MarkMenusSink(marker)(_CONN)

    assert marker.marks == 1


def test_a_silent_presence_marks_nothing_anywhere() -> None:
    binder = _Binder()

    MenuPresence.silent().announce("gained", _CONN, binder)

    assert len(binder.bound) == 1  # the sink is bound; firing it does nothing
    binder.bound[0][1](_CONN)  # raises nothing: there is no replicator to mark


@final
class _SceneMarker:
    """A DirtyMarker recording which scenes were marked."""

    scenes: list[SceneId]
    __slots__ = ("scenes",)

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self.scenes = []
        return self

    def mark_dirty(self, scene_id: SceneId) -> None:
        self.scenes.append(scene_id)

    def mark_menus(self) -> None:
        raise AssertionError("a rename must not mark the menus")


def test_renamed_scenes_are_each_marked_dirty() -> None:
    marker = _SceneMarker()

    MenuPresence(marker, MarkMenusSink(marker)).scenes_renamed(
        [SceneId("s1"), SceneId("s2")]
    )

    assert marker.scenes == [SceneId("s1"), SceneId("s2")]


def test_no_renamed_scene_marks_nothing() -> None:
    marker = _SceneMarker()

    MenuPresence(marker, MarkMenusSink(marker)).scenes_renamed(())

    assert marker.scenes == []
