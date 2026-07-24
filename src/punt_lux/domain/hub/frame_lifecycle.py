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

import logging
from typing import TYPE_CHECKING, Protocol, Self, final, runtime_checkable

if TYPE_CHECKING:
    from punt_lux.domain.hub.frame_expiry import FrameExpiry
    from punt_lux.domain.hub.scene_presentation import (
        ScenePresentation,
        ScenePresentationRegistry,
    )
    from punt_lux.domain.hub.store_lock import StoreLock
    from punt_lux.domain.ids import SceneId

__all__ = ["FrameLifecycle", "SceneRootRemover"]

logger = logging.getLogger(__name__)


@runtime_checkable
class SceneRootRemover(Protocol):
    """The one teardown operation FrameLifecycle needs — the ``SubtreeRemover`` side.

    A structural interface so the lifecycle depends on the teardown it uses, not on
    the whole remover, and a test can drive it with a fake.
    """

    def drop_scene_roots(self, scene_id: SceneId) -> None:
        """Tear down every root of ``scene_id`` whatever its owner."""
        ...


@final
class FrameLifecycle:
    """Own each scene's presentation, its TTL deadline, and its teardown, under lock."""

    _frames: ScenePresentationRegistry
    _remover: SceneRootRemover
    _expiry: FrameExpiry
    _lock: StoreLock
    __slots__ = ("_expiry", "_frames", "_lock", "_remover")

    def __new__(
        cls,
        frames: ScenePresentationRegistry,
        remover: SceneRootRemover,
        expiry: FrameExpiry,
        lock: StoreLock,
    ) -> Self:
        self = super().__new__(cls)
        self._frames = frames
        self._remover = remover
        self._expiry = expiry
        self._lock = lock
        return self

    def present(
        self,
        scene_id: SceneId,
        presentation: ScenePresentation,
        ttl_seconds: float | None,
    ) -> None:
        """Record how a scene is framed and arm its frame's TTL, in one locked step.

        Recording the presentation and arming the deadline is a single method, so
        a caller cannot install a frame yet forget to (re-)arm it: the atomicity
        the sweep relies on is a property of this method, not a convention the
        caller must uphold. A ``ttl_seconds`` of None clears any prior deadline, so
        a re-show without a TTL makes the frame permanent.
        """
        with self._lock.write():
            self._frames.record(scene_id, presentation)
            self._expiry.set_deadline(presentation.frame_id, ttl_seconds)

    def record(self, scene_id: SceneId, presentation: ScenePresentation) -> None:
        """Remember how a scene is framed, without touching its TTL.

        The presentation half of :meth:`present`, kept for callers (and tests) that
        set up or refresh a frame's presentation with no bearing on its deadline.
        """
        with self._lock.write():
            self._frames.record(scene_id, presentation)

    def forget(self, scene_id: SceneId) -> None:
        """Drop a scene's presentation; disarm its frame's TTL once the frame empties.

        A blanked scene's frame should not keep a live deadline the sweep would
        later wake to act on for nothing. Once this scene is forgotten, if no other
        scene remains in its frame the frame's deadline is disarmed. Idempotent.
        """
        with self._lock.write():
            frame_id = self._frames.presentation_for(scene_id).frame_id
            self._frames.forget(scene_id)
            if not self._frames.scenes_in_frame(frame_id):
                self._expiry.disarm(frame_id)

    def presentation_for(self, scene_id: SceneId) -> ScenePresentation:
        """Return how a scene was shown, or a self-framed default, read under lock."""
        with self._lock.read():
            return self._frames.presentation_for(scene_id)

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

        The whole sweep runs under one write lock, so expiring a frame and tearing
        down its scenes is atomic against a concurrent re-show. Frames are isolated
        from one another the way ``Hub.publish`` isolates subscribers: each is torn
        down and only then disarmed, and a frame whose tear-down raises is logged
        and left armed to retry on the next sweep — it never consumes the frame nor
        aborts the others. Every frame that *did* tear down is in the returned set
        regardless, so the caller repaints it even when a later frame fails; a
        returned frame is never stranded (torn down on the Hub but never blanked).
        Tear-down work runs while the store lock is held, so it must stay bounded —
        a scene-roots removal, nothing heavier.
        """
        with self._lock.write():
            scenes: set[SceneId] = set()
            for frame_id in self._expiry.due_frames():
                try:
                    torn = self._tear_down(frame_id)
                except Exception:
                    logger.exception(
                        "frame %s tear-down failed; leaving its TTL armed to retry",
                        frame_id,
                    )
                    continue
                scenes |= torn
                self._expiry.disarm(frame_id)
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
