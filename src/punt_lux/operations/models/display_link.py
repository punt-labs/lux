"""The Hub's observed display-link state (DisplayLinkage, design §6/§9).

Split into two discriminated shapes rather than one model with an optional
``retry_delay_seconds: float | None`` -- a connected link never has a pending
retry delay, so the field does not exist on that shape at all (PY-TS-14)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

__all__ = ["ConnectedLinkState", "DisconnectedLinkState", "DisplayLinkState"]


class ConnectedLinkState(BaseModel):
    """The display is connected — idle or actively receiving scenes."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["connected"] = "connected"
    linkage: Literal["connected_idle", "connected_active"]
    live_scene_count: int
    hub_host: str  # socket.gethostname() -- which machine this Hub is on
    hub_pid: int  # os.getpid() -- which Hub process, for a same-host duplicate


class DisconnectedLinkState(BaseModel):
    """No display is connected; content held is retried at a paced cadence."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["disconnected"] = "disconnected"
    linkage: Literal["disconnected", "held"]
    live_scene_count: int
    retry_delay_seconds: float
    hub_host: str
    hub_pid: int


# The two shapes a caller discriminates on ``kind`` — never a single model
# with an optional retry field.
type DisplayLinkState = ConnectedLinkState | DisconnectedLinkState
