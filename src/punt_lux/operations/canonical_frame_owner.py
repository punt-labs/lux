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

    def facts_for_frame(self, frame_id: str) -> tuple[tuple[str, str], ...] | None:
        """Return the frame's canonical owner rows, or ``None`` if none is owned."""
        canonical = self._canonical_scene(frame_id)
        return None if canonical is None else self._facts.facts_for(canonical)

    def _canonical_scene(self, frame_id: str) -> SceneId | None:
        """Return the senior owned scene of ``frame_id``; ``None`` if none is owned.

        The frame's live scenes are walked in first-appearance order -- the
        order in which they first received a root, which ``live_scene_ids`` and
        ``scene_owners`` both preserve -- and the first that still has a root
        owner is the canonical one. Seniority is defined by registration order
        everywhere else, so the owner is the frame's earliest-appearing owned
        scene and depends only on the frame's membership, never on which scene
        was sent last.
        """
        frames = self._display.frames
        owned_in_frame = (
            sid
            for sid in self._display.live_scene_ids()
            if frames.presentation_for(sid).frame_id == frame_id
            and self._display.scene_owners(sid)
        )
        return next(owned_in_frame, None)
