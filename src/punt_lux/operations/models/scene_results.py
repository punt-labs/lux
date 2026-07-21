"""The success results a scene mutation returns."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

__all__ = ["Cleared", "SceneShown"]


class SceneShown(BaseModel):
    """A scene was installed and marked for resend."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["ok"] = "ok"
    scene_id: str


class Cleared(BaseModel):
    """Every scene the caller owned was removed and the display blanked."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["ok"] = "ok"
