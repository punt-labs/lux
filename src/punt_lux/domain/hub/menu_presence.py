"""MenuPresence — what a change to who the Clients menu lists owes the Hub.

A change to who the menu lists is also a change to what a connection is
*called*, and a label is part of a window's title, so the same debt-payer
retitles the connection's scenes (:meth:`MenuPresence.retitle_scenes`): both are
marks on the one replicator, owed by the same transitions.

Every transition that changes which sessions earn a menu entry owes the rest of
the Hub two things, in the same critical section: a mark, so the replicator
re-reads the roster and re-pushes it, and exactly one departure sink bound for the
session, so its departure marks the entry away. ``HubDisplay`` performs the
transition under the store lock; this is the object it asks to pay the debt.

The sink is one shared object per Hub that captures no session, so binding it
again is a no-op under :class:`~punt_lux.domain.hub.departure_sinks.DepartureSinks`'
equality dedup. A sink built per attach would never compare equal to the last, and
each would pin the session that made it for the life of the process.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, Self, final

from punt_lux.domain.hub.null_dirty_marker import NullDirtyMarker

if TYPE_CHECKING:
    from collections.abc import Iterable

    from punt_lux.domain.hub.departure_sinks import DepartureSink
    from punt_lux.domain.hub.menu_listing import PresenceChange
    from punt_lux.domain.hub.replicator_ports import DirtyMarker
    from punt_lux.domain.ids import ConnectionId, SceneId

__all__ = ["MarkMenusSink", "MenuPresence", "SinkBinder"]


class SinkBinder(Protocol):
    """Where a departure sink is bound: the cascade that fires it on departure."""

    def bind_sink(self, connection_id: ConnectionId, sink: DepartureSink) -> None:
        """Bind ``sink`` to ``connection_id``'s departure."""
        ...


@final
class MarkMenusSink:
    """The departure sink that re-pushes the menus; captures no session."""

    _marker: DirtyMarker
    __slots__ = ("_marker",)

    def __new__(cls, marker: DirtyMarker) -> Self:
        self = super().__new__(cls)
        self._marker = marker
        return self

    def __call__(self, _connection_id: ConnectionId, /) -> None:
        """Mark the menus: the departed session's entry is to be withdrawn."""
        self._marker.mark_menus()


@final
class MenuPresence:
    """The marker and the one shared departure sink a presence change pays to."""

    _marker: DirtyMarker
    _sink: DepartureSink
    __slots__ = ("_marker", "_sink")

    def __new__(cls, marker: DirtyMarker, sink: DepartureSink) -> Self:
        self = super().__new__(cls)
        self._marker = marker
        self._sink = sink
        return self

    @classmethod
    def silent(cls) -> Self:
        """Presence that marks nothing, before the real replicator is wired in."""
        marker = NullDirtyMarker()
        return cls(marker, MarkMenusSink(marker))

    def announce(
        self, change: PresenceChange, connection_id: ConnectionId, binder: SinkBinder
    ) -> None:
        """Mark the menus and bind the sink, unless ``change`` changed nothing."""
        if change != "unchanged":
            self.arm(connection_id, binder)
            self._marker.mark_menus()

    def retitle_scenes(self, scene_ids: Iterable[SceneId]) -> None:
        """Mark each scene dirty: its owner's name moved, so its title is stale.

        A name moves when a group's last member departs or when a connection is
        first named; the scenes then resend with the owner's current label.
        """
        for scene_id in scene_ids:
            self._marker.mark_dirty(scene_id)

    def arm(self, connection_id: ConnectionId, binder: SinkBinder) -> None:
        """Bind the one shared sink for ``connection_id``; repeating is a no-op."""
        binder.bind_sink(connection_id, self._sink)
