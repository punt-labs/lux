"""The frame-state request and the raw echo a string-return setter formats.

The setters that keep a legacy string return (``set_theme``,
``set_window_settings``, ``set_frame_state``) succeed with a :class:`DisplayAck`.
It carries the display's own reply payload so the adapter can format the exact
legacy line — a theme name, a JSON dump of the changed fields — without a typed
model per setter, since each setter's legacy string is a different projection of
that payload.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from punt_lux.operations.models.common import OpError

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ["DisplayAck", "FrameStatePatch"]


class FrameStatePatch(BaseModel):
    """A change to a frame's transient minimize state."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    minimized: bool | None = None  # None leaves the frame's minimize state as-is

    @classmethod
    def parse(cls, raw: Mapping[str, object]) -> FrameStatePatch | OpError:
        """Validate raw arguments, or return an ``OpError`` instead of raising."""
        try:
            return cls.model_validate(raw)
        except ValidationError as exc:
            return OpError.from_validation(exc)


class DisplayAck(BaseModel):
    """A display write succeeded; ``payload`` is the display's own reply."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["ok"] = "ok"
    # The display's reply shape, formatted per-setter by the adapter (PY-TS-14
    # wire boundary — each setter's legacy string is its own projection of this).
    payload: dict[str, object]
