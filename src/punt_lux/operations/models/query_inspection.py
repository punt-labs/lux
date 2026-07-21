"""SceneInspection — a scene's element tree with render path and resolved props.

Read from ``HubDisplay`` — the authority — not the display replica. Each element
reports whether it is on the Element-ABC path or the legacy path and its resolved
state including defaults, so a migration is verified without inspecting pixels.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

__all__ = ["InspectedElement", "SceneInspection"]


class InspectedElement(BaseModel):
    """One element's identity, render path, resolved state, and children."""

    model_config = ConfigDict(frozen=True)

    id: str
    kind: str
    render_path: Literal["abc", "legacy"]
    # Resolved element state including defaults. A wire-shaped map because the
    # element kinds are open and each fills its own props; narrowed per kind by
    # the element codec, not here (PY-TS-14 wire boundary).
    resolved_props: dict[str, object]
    children: list[InspectedElement] = []


class SceneInspection(BaseModel):
    """A scene's inspected element tree, read from the authoritative store."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["ok"] = "ok"
    scene_id: str
    elements: list[InspectedElement]
    # A display-side mirror check; None when not requested. Never read as Hub
    # authority (introspection-api.md).
    domain_mirror_present: bool | None = None
