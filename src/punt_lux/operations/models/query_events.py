"""RecentEvents — the display's ring buffer of recent interactions, proxied."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from punt_lux.operations.models.common import OpError

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ["InteractionEvent", "RecentEvents"]


class InteractionEvent(BaseModel):
    """One interaction the display recorded."""

    model_config = ConfigDict(frozen=True)

    element_id: str
    action: str  # open-ended interaction name (clicked, changed, ...)
    value: object | None = None  # the new value for value-bearing widgets
    timestamp: float


class RecentEvents(BaseModel):
    """The last N interactions and how many are buffered."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["ok"] = "ok"
    events: list[InteractionEvent]
    total_buffered: int

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> RecentEvents | OpError:
        """Build from the display's ``list_recent_events`` reply, or reject it."""
        try:
            return cls.model_validate(payload)
        except ValidationError as exc:
            return OpError.from_reply(exc)
