"""SceneGeometry — the display's painted rects as a discriminated state.

Read by proxying the display's ``inspect_scene`` with a geometry flag. The live
rects are display-local truth — the dragged position and ImGui's auto-sizing
outcome — so they cross back as this read, never as Hub state. The three cases
keep "you didn't ask" (``not_requested``), "you asked and I couldn't tell"
(``unavailable``), and "here they are" (``present``) from ever being confused,
the same shape ``MirrorState`` uses. An element in the tree but absent from
``present.elements`` was not painted last frame; absence reports that directly.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Literal, Self, cast

from pydantic import BaseModel, ConfigDict, Field

from punt_lux.protocol.geometry import Rect

__all__ = [
    "GeometryNotRequested",
    "GeometryPresent",
    "GeometryUnavailable",
    "SceneGeometry",
]


class GeometryNotRequested(BaseModel):
    """The caller did not ask for painted geometry."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["not_requested"] = "not_requested"


class GeometryUnavailable(BaseModel):
    """Geometry was requested but could not be answered.

    A display that is down, a timed-out round-trip, or a malformed reply — the
    ``reason`` carries which. Distinct from ``not_requested`` so a caller can
    tell "you didn't ask" from "you asked and I couldn't tell".
    """

    model_config = ConfigDict(frozen=True)

    kind: Literal["unavailable"] = "unavailable"
    reason: str


class GeometryPresent(BaseModel):
    """The painted rects of the display's last completed frame.

    ``elements`` maps each painted element id to its screen rect; an element not
    painted last frame is absent. ``frame`` is the scene's frame rect, or absent
    when that frame was not painted.
    """

    model_config = ConfigDict(frozen=True)

    kind: Literal["present"] = "present"
    frame: Rect | None = None
    elements: dict[str, Rect] = {}

    @classmethod
    def from_block(cls, block: Mapping[str, object]) -> Self:
        """Decode the display's ``geometry`` reply block, raising on malformed."""
        raw_elements = block.get("elements")
        if not isinstance(raw_elements, Mapping):
            msg = f"geometry 'elements' must be a mapping; got {raw_elements!r}"
            raise ValueError(msg)
        elements = {
            str(eid): cls._rect(rect)
            for eid, rect in cast("Mapping[str, object]", raw_elements).items()
        }
        raw_frame = block.get("frame")
        frame = cls._rect(raw_frame) if raw_frame is not None else None
        return cls(frame=frame, elements=elements)

    @staticmethod
    def _rect(raw: object) -> Rect:
        """Decode one wire rect, raising ``ValueError`` if it is not a mapping."""
        if not isinstance(raw, Mapping):
            msg = f"geometry rect must be a mapping; got {raw!r}"
            raise ValueError(msg)
        return Rect.from_dict(cast("dict[str, object]", raw))


# Discriminated so "not requested", "unavailable", and "present" never confuse.
SceneGeometry = Annotated[
    GeometryNotRequested | GeometryUnavailable | GeometryPresent,
    Field(discriminator="kind"),
]
