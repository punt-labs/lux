"""DisplayStateSnapshot — the Display's own widget/frame state, read once.

Curated so a caller can compare the Display's steady-state facts against the
Hub's own view of a scene or frame. Read-only and proxied, like every other
display fact this codebase reports (see ``operations/display_facts.py`` and
``operations/frame_visibility_proxy.py``) — never installed as Hub state.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, NonNegativeInt

from punt_lux.operations.models.query_visibility import FrameVisibility

__all__ = ["DisplayStateSnapshot", "FramePresentation", "WidgetSnapshot"]

# WidgetState's keys are the per-render-frame bookkeeping vocabulary each
# ImGui renderer privately owns (display/replica/widget_state.py); Lux does
# not recreate a typed domain model for arbitrary renderer-defined keys here
# (PY-TS-14 wire boundary) — the curated set of names
# ``WidgetState.observable_snapshot`` emits is the contract, not this value's
# type.
type WireScalar = str | float | bool | tuple[str, ...]


class WidgetSnapshot(BaseModel):
    """One scene's curated Display-local widget state, keyed by element id."""

    model_config = ConfigDict(frozen=True)

    values: dict[str, WireScalar]


class FramePresentation(BaseModel):
    """One frame's Display-owned facts (DES-088) — never Hub-authoritative."""

    model_config = ConfigDict(frozen=True)

    frame_id: str
    visibility: FrameVisibility
    # None is a real state, not "unknown": a frame with no scenes has no
    # active tab to report.
    active_tab: str | None
    cascade_index: NonNegativeInt


class DisplayStateSnapshot(BaseModel):
    """The Display's own state, read once, for Hub-vs-Display comparison."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["ok"] = "ok"
    scenes: dict[str, WidgetSnapshot]
    frames: list[FramePresentation]
