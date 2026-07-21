"""DisplayInfo — the display process's own metadata, as a typed result.

This model is both the ``get_display_info`` operation's result type and the
single source its MCP output schema is generated from. Because one model is both
sides, a payload the model accepts cannot be rejected by a schema built from the
model — which is exactly the drift the hand-maintained schema used to suffer.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict

from punt_lux.operations.models.common import OpError

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ["DisplayInfo"]


class DisplayInfo(BaseModel):
    """The running display's backend, geometry, frame rate, and identity."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["ok"] = "ok"
    backend: str
    window_width: int
    window_height: int
    fps: float
    pid: int
    uptime_seconds: float
    protocol_version: str
    element_kinds: int

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> DisplayInfo | OpError:
        """Build from the display's reply, or an ``OpError`` if it is malformed."""
        try:
            return cls.model_validate(payload)
        except ValueError as exc:
            return OpError(code="rejected", reason=str(exc))
