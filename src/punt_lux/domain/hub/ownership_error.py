"""Typed exception raised when a connection mutates an element it does not own.

The Hub apply pipeline propagates failures through exceptions; the Display
apply pipeline propagates them through discriminated ``Error`` returns. The
two surfaces share the same vocabulary but the carrier differs.
"""

from __future__ import annotations

from dataclasses import dataclass

from punt_lux.domain.ids import ConnectionId, ElementId, SceneId

__all__ = ["HubOwnershipError"]


@dataclass(frozen=True, slots=True)
class HubOwnershipError(PermissionError):
    """Raised when a connection mutates an element it does not own."""

    scene_id: SceneId
    element_id: ElementId
    attempting: ConnectionId
    owning: ConnectionId

    def __str__(self) -> str:
        return (
            f"connection {self.attempting!r} cannot mutate element "
            f"{self.element_id!r} in scene {self.scene_id!r}: owned by "
            f"{self.owning!r}"
        )
