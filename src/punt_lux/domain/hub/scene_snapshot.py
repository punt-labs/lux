"""SceneReader and SceneSnapshot — the store's read side for the replicator.

The replicator must never encode live store elements. A scene root can mutate in
place — a continuous-edit widget applies a field patch, and an ``apply_patch``
that fails clears and rebuilds the element's ``vars`` mid-rollback — so reading
one while the wire encoder walks it tears the encode. ``SceneReader`` hands out a
``SceneSnapshot`` instead: a deep copy of the roots taken under the store read
lock, paired with the presentation to resend them with. The copy is independent
of the store, so the replicator pushes it after the lock is released and the
store lock and the client send lock are never held together.

Deep-copying is faithful because it honours each element's own reduction: an ABC
root's ``__reduce__`` drops the HubDisplay-bound observers and keeps its handlers,
exactly as the Hub-to-Display wire does, and the copy stays the same type, so it
serializes to the identical bytes the live element would have.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from punt_lux.domain.element import Element as WireElement
    from punt_lux.domain.hub.element_index import ElementIndex
    from punt_lux.domain.hub.scene_presentation import (
        ScenePresentation,
        ScenePresentationRegistry,
        ScenePusher,
    )
    from punt_lux.domain.hub.store_lock import StoreLock
    from punt_lux.domain.ids import SceneId

__all__ = ["SceneReader", "SceneSnapshot"]


@final
@dataclass(frozen=True, slots=True)
class SceneSnapshot:
    """A scene copied out of the store, ready to resend without further reads.

    Holds the deep-copied roots and the presentation. ``push`` sends the copy;
    a snapshot of a since-cleared scene holds no roots and pushes nothing — the
    clear already blanked the display, so repainting an empty framed show would
    only re-open a blank frame.
    """

    _scene_id: SceneId
    _roots: tuple[WireElement, ...]
    _presentation: ScenePresentation

    def push(self, sender: ScenePusher) -> None:
        """Resend the copied scene through ``sender``; a no-op when empty."""
        if self._roots:
            self._presentation.push(sender, self._scene_id, self._roots)


@final
class SceneReader:
    """The store's replicator-facing read side: locked snapshots and live ids.

    Composes the element index, the presentation registry, and the store lock,
    and holds the read lock only long enough to copy a scene's state out — so
    the lock discipline lives here, in the store, and never escapes to the
    replicator that calls it.
    """

    _index: ElementIndex
    _frames: ScenePresentationRegistry
    _lock: StoreLock
    __slots__ = ("_frames", "_index", "_lock")

    def __new__(
        cls,
        index: ElementIndex,
        frames: ScenePresentationRegistry,
        lock: StoreLock,
    ) -> Self:
        self = super().__new__(cls)
        self._index = index
        self._frames = frames
        self._lock = lock
        return self

    def snapshot(self, scene_id: SceneId) -> SceneSnapshot:
        """Copy a scene's roots and presentation out under the read lock."""
        with self._lock.read():
            roots = tuple(deepcopy(r) for r in self._index.scene_roots(scene_id))
            presentation = self._frames.presentation_for(scene_id)
        return SceneSnapshot(scene_id, roots, presentation)

    def live_scene_ids(self) -> tuple[SceneId, ...]:
        """Return every scene still holding a non-removed root, read under lock."""
        with self._lock.read():
            return tuple(s for s in self._index.scenes() if self._index.scene_roots(s))
