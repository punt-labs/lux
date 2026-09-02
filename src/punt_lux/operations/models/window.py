"""Window settings — the current-settings result."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from punt_lux.operations.models.common import OpError

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ["WindowSettings"]

# The reported font_scale range -- the display's own bound on the field, kept
# beside the result type it validates rather than duplicated by a caller.
_FONT_SCALE_RANGE = (0.5, 3.0)


class WindowSettings(BaseModel):
    """The window's opacity, font scale, decoration, and idle frame rate."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["ok"] = "ok"
    opacity: float
    # Bounded: a reply outside the scale range (e.g. a raw pixel size echoed by
    # mistake) is malformed, not a settings value.
    font_scale: float = Field(ge=_FONT_SCALE_RANGE[0], le=_FONT_SCALE_RANGE[1])
    decorated: bool
    fps_idle: float

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> WindowSettings | OpError:
        """Build from the display's ``get_window_settings`` reply, or reject it.

        The display owns and reports every field; a reply missing one, or a
        ``font_scale`` outside its range, is malformed and rejected loudly rather
        than papered over.
        """
        try:
            return cls.model_validate(payload)
        except ValidationError as exc:
            return OpError.from_reply(exc)
