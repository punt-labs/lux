"""The Hub's named, pinned connection to a Display."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class HubConnected(BaseModel, frozen=True):
    """A dial identity names a connection, not the Display process lifetime."""

    state: Literal["connected"] = "connected"
    name: str = Field(min_length=1)
