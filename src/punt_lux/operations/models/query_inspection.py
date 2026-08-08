"""SceneInspection — a scene's element tree with resolved props.

Read from ``HubDisplay`` — the authority — not the display replica. Each
element reports its resolved state including defaults, so behavior is
verified without inspecting pixels. One proxied display fact hangs off the
inspection when asked: the painted geometry (:mod:`.query_geometry`).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from punt_lux.operations.models.query_geometry import (
    GeometryNotRequested,
    SceneGeometry,
)

__all__ = ["InspectedElement", "SceneInspection"]


class InspectedElement(BaseModel):
    """One element's identity, resolved state, and children."""

    model_config = ConfigDict(frozen=True)

    id: str
    kind: str
    # Resolved element state including defaults. A wire-shaped map because the
    # element kinds are open and each fills its own props; narrowed per kind by
    # the element codec, not here (PY-TS-14 wire boundary).
    resolved_props: dict[str, object]
    children: list[InspectedElement] = Field(
        default_factory=lambda: list[InspectedElement]()
    )


class SceneInspection(BaseModel):
    """A scene's inspected element tree, read from the authoritative store."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["ok"] = "ok"
    scene_id: str
    elements: list[InspectedElement]
    geometry: SceneGeometry = GeometryNotRequested()
