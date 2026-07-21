"""SceneList — the Hub-authoritative view of every live scene and frame."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

__all__ = ["FrameSummary", "SceneList", "SceneSummary"]


class SceneSummary(BaseModel):
    """One scene the Hub is holding: its size, frame, and owner."""

    model_config = ConfigDict(frozen=True)

    scene_id: str
    element_count: int
    frame_id: str | None  # None when the scene is not shown into a frame
    owner: str | None  # the owning connection id, None if unowned


class FrameSummary(BaseModel):
    """One frame and the scenes it presents."""

    model_config = ConfigDict(frozen=True)

    frame_id: str
    title: str
    scene_count: int
    scene_ids: list[str]
    layout: Literal["tab", "stack"]


class SceneList(BaseModel):
    """Every live scene and frame, read from the authoritative store."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["ok"] = "ok"
    scenes: list[SceneSummary]
    frames: list[FrameSummary]
