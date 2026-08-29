"""SceneList — the Hub-authoritative view of every live scene and frame."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from punt_lux.operations.models.query_ownership import SceneOwner
from punt_lux.operations.models.query_quarantine import QuarantineInfo
from punt_lux.operations.models.query_visibility import (
    FrameVisibilityState,
    VisibilityNotRequested,
)

__all__ = ["FrameSummary", "SceneList", "SceneSummary"]


class SceneSummary(BaseModel):
    """One scene the Hub is holding: its size, frame, and owning connections."""

    model_config = ConfigDict(frozen=True)

    scene_id: str  # the composed store key (DES-086)
    local_id: str  # the caller's own id, as it declared it
    element_count: int
    frame_id: str  # total: an unframed scene defaults to a frame named by its id
    # Every distinct owner of a root in the scene, first-appearance order; empty
    # when unowned, plural because a scene can hold roots from several sessions.
    owners: list[SceneOwner]
    status: Literal["live", "quarantined"] = "live"
    # Present only when status is "quarantined" — a discriminated companion
    # field, not a value the type system gave up on (PY-TS-14).
    quarantine: QuarantineInfo | None = None


class FrameSummary(BaseModel):
    """One frame, the scenes it presents, and where the display is showing it."""

    model_config = ConfigDict(frozen=True)

    frame_id: str
    title: str
    scene_count: int
    scene_ids: list[str]
    layout: Literal["tab", "stack"]
    # Proxied from the running display, never Hub authority: the user owns where
    # a window sits and it is never replicated back (DES-088). Off unless the
    # caller asks, so a bare list_scenes stays one Hub-local read; discriminated
    # rather than nullable, so "not asked" and "could not answer" cannot be read
    # as "on screen".
    visibility: FrameVisibilityState = VisibilityNotRequested()


class SceneList(BaseModel):
    """Every scene and frame from the authoritative store, live or quarantined.

    Each :class:`SceneSummary` carries a ``status`` discriminator and, when
    quarantined, a :class:`QuarantineInfo` — quarantine is a replication
    decision, not a deletion, so this introspection view keeps quarantined
    scenes visible for the agents that own them.
    """

    model_config = ConfigDict(frozen=True)

    kind: Literal["ok"] = "ok"
    scenes: list[SceneSummary]
    frames: list[FrameSummary]
