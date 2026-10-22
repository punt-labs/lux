"""CanonicalFrameOwner — owner facts keyed to a frame, not to a single scene.

The replicator resends each scene of a frame separately, and a frame can compose
scenes owned by different connections. Resolving owner facts per scene would let
the popup show whichever scene was sent last. This reader wraps
:class:`~punt_lux.operations.frame_owner_facts.FrameOwnerFacts` and lifts the
resolution to the frame: it picks the frame's canonical scene and asks the inner
reader for that scene's facts, so every scene-send for a frame carries identical
facts.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, cast, final

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
        """Return the oldest live scene of ``frame_id``; ``None`` if it holds none.

        "Oldest" is the frame's own entry order -- the order of the Display's
        ``Frame.scene_order`` -- so the Display can tell locally whether a
        departing scene was the canonical one.
        """
        live = frozenset(self._display.live_scene_ids())
        return next(filter(live.__contains__, self._entrants(frame_id)), None)

    def _entrants(self, frame_id: str) -> list[SceneId]:
        """Return the scenes shown in ``frame_id``, oldest entrant first.

        A scene never explicitly shown is framed by its own id, so with nothing
        recorded it is the sole entrant of the frame that id names.
        """
        frames = self._display.frames
        recorded = frames.scenes_in_frame(frame_id)
        own = cast("SceneId", frame_id)  # a never-shown scene is framed by its id
        is_own = frames.presentation_for(own).frame_id == frame_id
        return recorded if recorded else [own] if is_own else []
