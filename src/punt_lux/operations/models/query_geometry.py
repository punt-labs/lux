"""SceneGeometry — the display's painted geometry as a discriminated state.

Read by proxying the display's ``inspect_scene`` with a geometry flag. The live
geometry is display-local truth — the dragged position, ImGui's auto-sizing
outcome, and the Z-order — so it crosses back as this read, never as Hub state.
The three cases keep "you didn't ask" (``not_requested``), "you asked and I
couldn't tell" (``unavailable``), and "here it is" (``present``) from ever being
confused, the same shape ``MirrorState`` uses. An element in the tree but absent
from ``present.elements`` was not painted last frame; absence reports that
directly.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Literal, Self, cast

from pydantic import BaseModel, ConfigDict, Field

from punt_lux.protocol.painted_geometry import ElementGeometry, FrameGeometry

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
    """The painted geometry of the display's last completed frame.

    ``elements`` maps each painted *named* element id to its geometry — the screen
    rect, the paint sequence, and the window stack index. ``anonymous`` maps the
    per-frame ``kind:sequence`` keys of elements with no id of their own (a
    separator). The two maps are separate because element ids are unconstrained,
    so a user id reading like ``separator:0`` must not collide with a synthesized
    anonymous key. An element not painted last frame is absent from its map;
    ``frame`` is the scene's frame geometry, or absent when it was not painted.
    """

    model_config = ConfigDict(frozen=True)

    kind: Literal["present"] = "present"
    frame: FrameGeometry | None = None
    elements: dict[str, ElementGeometry] = Field(default_factory=dict)
    anonymous: dict[str, ElementGeometry] = Field(default_factory=dict)

    @classmethod
    def from_block(cls, block: Mapping[str, object]) -> Self:
        """Decode the display's ``geometry`` reply block, raising on malformed."""
        elements = cls._decode_map(block, "elements")
        anonymous = cls._decode_map(block, "anonymous")
        raw_frame = block.get("frame")
        frame = (
            FrameGeometry.from_dict(cls._entry(raw_frame))
            if raw_frame is not None
            else None
        )
        return cls(frame=frame, elements=elements, anonymous=anonymous)

    @classmethod
    def _decode_map(
        cls, block: Mapping[str, object], field: str
    ) -> dict[str, ElementGeometry]:
        """Decode one keyed geometry map from the block, raising a named error."""
        raw = block.get(field)
        if not isinstance(raw, Mapping):
            msg = f"geometry {field!r} must be a mapping; got {raw!r}"
            raise ValueError(msg)
        return {
            str(key): ElementGeometry.from_dict(cls._entry(entry))
            for key, entry in cast("Mapping[str, object]", raw).items()
        }

    @staticmethod
    def _entry(raw: object) -> dict[str, object]:
        """Return the wire mapping for one geometry entry, or raise if it is not."""
        if not isinstance(raw, Mapping):
            msg = f"geometry entry must be a mapping; got {raw!r}"
            raise ValueError(msg)
        return dict(cast("Mapping[str, object]", raw))


# Discriminated so "not requested", "unavailable", and "present" never confuse.
SceneGeometry = Annotated[
    GeometryNotRequested | GeometryUnavailable | GeometryPresent,
    Field(discriminator="kind"),
]
