"""SceneSubmission — a scene offered for installation: its roots, name, frame, life.

What every install takes, whether the tree came off the wire or the Hub built it
itself. The four values are decided together and used together — the request that
names a scene names its elements, the frame they go in, and the deadline they
live under — so they travel as one value and the gate can accept or reject the
whole of it.

The frame is a :class:`~punt_lux.domain.hub.scene_presentation.ScenePresentation`,
which this composes: the presentation is the frame's own id, title, and size,
while a submission is the whole offering.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Self

from punt_lux.domain.ids import SceneId

if TYPE_CHECKING:
    from collections.abc import Sequence

    from punt_lux.domain.element import Element as DomainElement
    from punt_lux.domain.hub.scene_presentation import ScenePresentation

__all__ = ["SceneSubmission"]


@dataclass(frozen=True, slots=True)
class SceneSubmission:
    """Element roots offered as one scene, with the frame and lifetime to show them."""

    elements: Sequence[DomainElement]
    scene_id: SceneId
    presentation: ScenePresentation
    # Absence is the contract: a frame with no deadline never expires, and a
    # re-show that names none clears whatever deadline the last one armed.
    ttl_seconds: float | None

    @classmethod
    def of(
        cls,
        elements: Sequence[DomainElement],
        scene_id: str,
        presentation: ScenePresentation,
        ttl_seconds: float | None,
    ) -> Self:
        """Offer the scene a surface named as a string — every wire scene id."""
        return cls(elements, SceneId(scene_id), presentation, ttl_seconds)

    @property
    def name(self) -> str:
        """The scene id as the surfaces spell it, for a result a caller reads."""
        return str(self.scene_id)
