"""SceneInspection — a scene's element tree with render path and resolved props.

Read from ``HubDisplay`` — the authority — not the display replica. Each element
reports whether it is on the Element-ABC path or the legacy path and its resolved
state including defaults, so a migration is verified without inspecting pixels.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "InspectedElement",
    "MirrorNotRequested",
    "MirrorPresent",
    "MirrorState",
    "MirrorUnavailable",
    "SceneInspection",
]


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


class MirrorNotRequested(BaseModel):
    """The caller did not ask for the display-side mirror check."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["not_requested"] = "not_requested"


class MirrorUnavailable(BaseModel):
    """The mirror check was requested but could not be answered.

    A display that is down, a timed-out round-trip, or a malformed reply — the
    ``reason`` carries which. Distinct from ``not_requested`` so a caller can tell
    "you didn't ask" from "you asked and I couldn't tell".
    """

    model_config = ConfigDict(frozen=True)

    kind: Literal["unavailable"] = "unavailable"
    reason: str


class MirrorPresent(BaseModel):
    """The mirror check was answered: whether every element is mirrored.

    ``present`` is the whole-scene answer — true only when the display holds a
    mirror for every element, since a partially-mirrored scene is not present.
    Never read as Hub authority (introspection-api.md).
    """

    model_config = ConfigDict(frozen=True)

    kind: Literal["present"] = "present"
    present: bool


# The display-side mirror check as a discriminated state, so "not requested",
# "requested but unavailable", and "answered" can never be confused.
MirrorState = Annotated[
    MirrorNotRequested | MirrorUnavailable | MirrorPresent,
    Field(discriminator="kind"),
]


class SceneInspection(BaseModel):
    """A scene's inspected element tree, read from the authoritative store."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["ok"] = "ok"
    scene_id: str
    elements: list[InspectedElement]
    mirror: MirrorState = MirrorNotRequested()
