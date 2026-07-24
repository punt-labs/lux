"""FrameLifecycle — a scene's frame, from how it is shown to how it is torn down.

Everything the store knows about a frame lives here: how each scene is framed for
a resend (its :class:`ScenePresentation`), its optional TTL deadline, and the two
ways it is torn down — a user closes it, or its time-to-live passes. All of it
sits behind one lock discipline rather than scattered across the store facade,
because a frame's presentation, its deadline, and its teardown must not be read or
written half-applied. This component composes the presentation registry, the
subtree remover (the teardown walk), the :class:`FrameExpiry` deadlines, and the
store lock.

Recording a presentation, arming a deadline, and sweeping expiry all take the same
lock every store write takes, so a frame re-armed with a fresh TTL is never torn
down by a stale deadline: the re-show's ``set_deadline`` and the sweep's
``expire_due`` serialize, and whichever runs second sees the other's effect.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from punt_lux.domain.hub.frame_expiry import FrameExpiry
    from punt_lux.domain.hub.scene_presentation import (
        ScenePresentation,
        ScenePresentationRegistry,
    )
    from punt_lux.domain.hub.store_lock import StoreLock
    from punt_lux.domain.hub.subtree_remover import SubtreeRemover
    from punt_lux.domain.ids import SceneId

__all__ = ["FrameLifecycle"]


@final
class FrameLifecycle:
    """Own each scene's presentation, its TTL deadline, and its teardown, under lock."""

    _frames: ScenePresentationRegistry
    _remover: SubtreeRemover
    _expiry: FrameExpiry
    _lock: StoreLock
    __slots__ = ("_expiry", "_frames", "_lock", "_remover")

    def __new__(
        cls,
        frames: ScenePresentationRegistry,
        remover: SubtreeRemover,
        expiry: FrameExpiry,
        lock: StoreLock,
    ) -> Self:
        self = super().__new__(cls)
        self._frames = frames
        self._remover = remover
        self._expiry = expiry
        self._lock = lock
        return self

    def record(self, scene_id: SceneId, presentation: ScenePresentation) -> None:
        """Remember how a scene was shown, for a later whole-scene resend."""
        with self._lock.write():
            self._frames.record(scene_id, presentation)

    def forget(self, scene_id: SceneId) -> None:
        """Drop a scene's presentation once a clear blanks it away. Idempotent."""
        with self._lock.write():
            self._frames.forget(scene_id)

    def presentation_for(self, scene_id: SceneId) -> ScenePresentation:
        """Return how a scene was shown, or a self-framed default, read under lock."""
        with self._lock.read():
            return self._frames.presentation_for(scene_id)

    def set_deadline(self, frame_id: str, ttl_seconds: float | None) -> None:
        """Arm ``frame_id`` at ``ttl_seconds``, or clear its deadline when None.

        Called inside the re-show's write lock so arming the deadline is atomic
        with installing the scene's roots.
        """
        with self._lock.write():
            self._expiry.set_deadline(frame_id, ttl_seconds)

    def remove_frame(self, frame_id: str) -> frozenset[SceneId]:
        """Close ``frame_id``: tear down its scenes, disarm its TTL, return them.

        Each scene's roots are dropped whatever the (possibly departed) owner, so
        an orphaned frame still closes, and the deadline is disarmed so a closed
        frame is never swept again.
        """
        with self._lock.write():
            self._expiry.disarm(frame_id)
            return self._tear_down(frame_id)

    def expire_due(self) -> frozenset[SceneId]:
        """Tear down every frame whose TTL has passed; return the scenes to repaint.

        Claim-and-remove runs under one write lock, so expiring a frame and tearing
        down its scenes is atomic against a concurrent re-show.
        """
        with self._lock.write():
            scenes: set[SceneId] = set()
            for frame_id in self._expiry.claim_due():
                scenes |= self._tear_down(frame_id)
            return frozenset(scenes)

    def seconds_until_next(self) -> float | None:
        """Return the wait until the soonest deadline, or None when none are armed."""
        with self._lock.read():
            return self._expiry.seconds_until_next()

    def _tear_down(self, frame_id: str) -> frozenset[SceneId]:
        """Drop the roots of every scene in ``frame_id``; return the scenes. Locked."""
        scenes = self._frames.scenes_in_frame(frame_id)
        for scene_id in scenes:
            self._remover.drop_scene_roots(scene_id)
        return frozenset(scenes)
