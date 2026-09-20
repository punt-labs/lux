"""CanonicalFrameOwner — owner facts keyed to a frame, not to a single scene.

The replicator resends each scene of a frame separately, and a frame can
compose several scenes owned by different connections. Resolving owner facts
per scene would let the popup show whichever scene was sent last. This reader
wraps :class:`~punt_lux.operations.frame_owner_facts.FrameOwnerFacts` and lifts
the resolution to the frame: it picks the frame's canonical scene and asks the
inner reader for that scene's facts, so every scene-send for a frame carries
identical facts.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.operations.frame_owner_facts import FrameOwnerFacts

if TYPE_CHECKING:
    from punt_lux.domain.hub.hub import Hub
    from punt_lux.domain.hub.hub_display import HubDisplay
    from punt_lux.domain.ids import SceneId
    from punt_lux.operations.ports import HubPorts

__all__ = ["CanonicalFrameOwner"]


@final
class CanonicalFrameOwner:
    """Resolve a frame's owner facts from every scene composed into the frame."""

    _display: HubDisplay
    _facts: FrameOwnerFacts
    __slots__ = ("_display", "_facts")

    def __new__(cls, display: HubDisplay, facts: FrameOwnerFacts) -> Self:
        self = super().__new__(cls)
        self._display = display
        self._facts = facts
        return self

    @classmethod
    def for_store(cls, display: HubDisplay, *, hub: Hub, ports: HubPorts) -> Self:
        """Wrap a store-wired :class:`FrameOwnerFacts` with frame-level lifting."""
        return cls(display, FrameOwnerFacts.for_store(display, hub=hub, ports=ports))

    def facts_for(self, scene_id: SceneId) -> tuple[tuple[str, str], ...] | None:
        """Return the frame's canonical owner rows, or ``None`` if unowned."""
        return self._facts.facts_for(self._canonical_scene(scene_id))

    def _canonical_scene(self, scene_id: SceneId) -> SceneId:
        """Return the senior owned scene of ``scene_id``'s frame, deterministic.

        The frame's live scenes are walked in a stable id order and the first
        that still has a root owner is the canonical one -- so the owner depends
        only on the frame's membership, never on which scene was sent last. With
        no owned scene, ``scene_id`` stands in and the inner reader reports it
        unowned.
        """
        frames = self._display.frames
        frame_id = frames.presentation_for(scene_id).frame_id
        cohort = sorted(
            (
                sid
                for sid in self._display.live_scene_ids()
                if frames.presentation_for(sid).frame_id == frame_id
            ),
            key=str,
        )
        for sid in cohort:
            if self._display.scene_owners(sid):
                return sid
        return scene_id
