"""SceneInspection — a scene's element tree with render path and resolved props.

Read from ``HubDisplay`` — the authority — not the display replica. Each element
reports its ``render_path`` (constant ``"abc"`` now that every kind is on the
Element-ABC path) and its resolved state including defaults, so behavior is
verified without inspecting pixels. Two proxied display facts hang off the
inspection when asked: the element mirror check (:mod:`.query_mirror`) and the
painted geometry (:mod:`.query_geometry`).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from punt_lux.operations.models.query_geometry import (
    GeometryNotRequested,
    SceneGeometry,
)
from punt_lux.operations.models.query_mirror import MirrorNotRequested, MirrorState

__all__ = ["InspectedElement", "SceneInspection"]


class InspectedElement(BaseModel):
    """One element's identity, render path, resolved state, and children."""

    model_config = ConfigDict(frozen=True)

    id: str
    kind: str
    # Constant post-migration: every kind is on the Element-ABC path. Kept so no
    # reader breaks; the type no longer advertises an unreachable ``"legacy"``.
    render_path: Literal["abc"]
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
    mirror: MirrorState = MirrorNotRequested()
    geometry: SceneGeometry = GeometryNotRequested()
