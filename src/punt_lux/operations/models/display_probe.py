"""Screenshot and ping results — display facts a probe reads back."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

__all__ = ["Pong", "Screenshot"]


class Screenshot(BaseModel):
    """A captured framebuffer image on the display host."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["ok"] = "ok"
    path: str


class Pong(BaseModel):
    """A completed ping round-trip."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["ok"] = "ok"
    rtt_seconds: float
