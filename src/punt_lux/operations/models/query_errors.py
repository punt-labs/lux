"""RecentErrors — the display's ring buffer of recent errors, proxied."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict

from punt_lux.operations.models.common import OpError

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ["DisplayErrorEntry", "RecentErrors"]


class DisplayErrorEntry(BaseModel):
    """One error or warning the display recorded."""

    model_config = ConfigDict(frozen=True)

    timestamp: float
    severity: Literal["error", "warning", "info"]
    message: str
    context: str


class RecentErrors(BaseModel):
    """The last N display-side errors and how many are buffered."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["ok"] = "ok"
    errors: list[DisplayErrorEntry]
    total_buffered: int

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> RecentErrors | OpError:
        """Build from the display's ``list_errors`` reply, or reject it."""
        try:
            return cls.model_validate(payload)
        except ValueError as exc:
            return OpError(code="rejected", reason=str(exc))
