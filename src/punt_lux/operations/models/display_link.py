"""The Hub's observed display-link state (DisplayLinkage, design §6/§9).

Split into two discriminated shapes rather than one model with an optional
``retry_delay_seconds: float | None`` -- a connected link never has a pending
retry delay, so the field does not exist on that shape at all (PY-TS-14)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

__all__ = ["ConnectedLinkState", "DisconnectedLinkState", "DisplayLinkState"]


class _HubIdentified:
    """Mix in the one thing both link shapes render the same way: whose Hub.

    No fields of its own -- ``hub_host``/``hub_pid`` are each shape's own
    pydantic fields -- so this never reopens the split-model question the
    module docstring settles; it only stops both shapes (and their callers)
    from re-deriving the same display string.
    """

    hub_host: str
    hub_pid: int

    @property
    def hub(self) -> str:
        """Return the compact ``hub=<host>:<pid>`` identity token."""
        return f"hub={self.hub_host}:{self.hub_pid}"


class ConnectedLinkState(_HubIdentified, BaseModel):
    """The display is connected — idle or actively receiving scenes."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["connected"] = "connected"
    linkage: Literal["connected_idle", "connected_active"]
    live_scene_count: int
    hub_host: str  # socket.gethostname() -- which machine this Hub is on
    hub_pid: int  # os.getpid() -- which Hub process, for a same-host duplicate


class DisconnectedLinkState(_HubIdentified, BaseModel):
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
