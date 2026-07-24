"""LockedPresentations — store-locked access to how each scene is framed.

The presentation half of ``HubDisplay``, split out so the facade delegates the
one concern — recording, forgetting, and reading a scene's
:class:`ScenePresentation` under the store lock — instead of carrying the lock
discipline inline. It composes the unlocked :class:`ScenePresentationRegistry`
with the store's :class:`StoreLock`, so every presentation access takes the same
lock the rest of the store's writes and reads take, and that discipline never
escapes to the caller.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from punt_lux.domain.hub.scene_presentation import (
        ScenePresentation,
        ScenePresentationRegistry,
    )
    from punt_lux.domain.hub.store_lock import StoreLock
    from punt_lux.domain.ids import SceneId

__all__ = ["LockedPresentations"]


@final
class LockedPresentations:
    """Record, forget, and read scene presentations under the store lock."""

    _frames: ScenePresentationRegistry
    _lock: StoreLock
    __slots__ = ("_frames", "_lock")

    def __new__(cls, frames: ScenePresentationRegistry, lock: StoreLock) -> Self:
        self = super().__new__(cls)
        self._frames = frames
        self._lock = lock
        return self

    def record(self, scene_id: SceneId, presentation: ScenePresentation) -> None:
        """Remember how a scene was shown, for a later whole-scene resend."""
        with self._lock.write():
            self._frames.record(scene_id, presentation)

    def forget(self, scene_id: SceneId) -> None:
        """Drop a scene's presentation once a clear blanks it away.

        A whole-display clear empties the scene and blanks the display, and
        nothing repaints it without a re-show recording a fresh presentation, so
        the entry is dead weight. Bounds the frame map on the clear path, as the
        replicator's post-blank reclaim does on the per-scene path.
        """
        with self._lock.write():
            self._frames.forget(scene_id)

    def presentation_for(self, scene_id: SceneId) -> ScenePresentation:
        """Return how a scene was shown, or a self-framed default, read under lock."""
        with self._lock.read():
            return self._frames.presentation_for(scene_id)
