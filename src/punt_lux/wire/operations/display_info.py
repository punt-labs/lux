"""DisplayInfo — the display process's own metadata, as a typed result.

This model is both the ``get_display_info`` operation's result type and the
single source its MCP output schema is generated from. Because one model is both
sides, a payload the model accepts cannot be rejected by a schema built from the
model — which is exactly the drift the hand-maintained schema used to suffer.
"""

from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict

from punt_lux.wire.operations.display_identity import DisplayIdentity

__all__ = ["DisplayInfo"]


class DisplayInfo(DisplayIdentity, frozen=True):
    """The running display's backend, geometry, frame rate, and identity."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["ok"] = "ok"
    backend: str
    window_width: int
    window_height: int
    fps: float
    element_kinds: int
