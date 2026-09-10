"""The Hub's observed display-link state (DisplayLinkage, design §6).

Split into two discriminated shapes rather than one model with an optional
``retry_delay_seconds: float | None`` — a connected link never has a pending
retry delay, so the field does not exist on that shape at all, instead of
existing and reading ``None`` (PY-TS-14 / OO Five Rules #5).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

__all__ = ["ConnectedLinkState", "DisconnectedLinkState", "DisplayLinkState"]


class ConnectedLinkState(BaseModel):
    """The display is connected — idle or actively receiving scenes."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["connected"] = "connected"
    linkage: Literal["connected_idle", "connected_active"]


class DisconnectedLinkState(BaseModel):
    """No display is connected; content held is retried at a paced cadence."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["disconnected"] = "disconnected"
    linkage: Literal["disconnected", "held"]
    retry_delay_seconds: float


# The two shapes a caller discriminates on ``kind`` — never a single model
# with an optional retry field.
type DisplayLinkState = ConnectedLinkState | DisconnectedLinkState
