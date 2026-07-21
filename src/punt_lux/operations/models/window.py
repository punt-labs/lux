"""Window settings — the current-settings result and the change request."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from punt_lux.operations.models.common import OpError

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = [
    "FONT_SCALE_RANGE",
    "FPS_IDLE_RANGE",
    "OPACITY_RANGE",
    "WindowSettings",
    "WindowSettingsPatch",
]

# The one source for each field's accepted range — the patch validates against
# these and the tool description is generated from them, so the accepted bounds
# and the advertised bounds cannot drift.
OPACITY_RANGE = (0.1, 1.0)
FONT_SCALE_RANGE = (0.5, 3.0)
FPS_IDLE_RANGE = (1.0, 120.0)


class WindowSettings(BaseModel):
    """The window's opacity, font scale, decoration, and idle frame rate."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["ok"] = "ok"
    opacity: float
    font_scale: float
    decorated: bool
    fps_idle: float

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> WindowSettings | OpError:
        """Build from the display's ``get_window_settings`` reply, or reject it.

        The display owns and reports every field; a reply missing one is
        malformed and rejected loudly rather than papered over.
        """
        try:
            return cls.model_validate(payload)
        except ValidationError as exc:
            return OpError.from_reply(exc)


class WindowSettingsPatch(BaseModel):
    """Only the provided fields change; a ``None`` field is left untouched."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    # None leaves the field unchanged; a provided value must be in range.
    opacity: float | None = Field(
        default=None, ge=OPACITY_RANGE[0], le=OPACITY_RANGE[1]
    )
    font_scale: float | None = Field(
        default=None, ge=FONT_SCALE_RANGE[0], le=FONT_SCALE_RANGE[1]
    )
    decorated: bool | None = None  # None leaves the decoration unchanged
    fps_idle: float | None = Field(
        default=None, ge=FPS_IDLE_RANGE[0], le=FPS_IDLE_RANGE[1]
    )

    @classmethod
    def parse(cls, raw: Mapping[str, object]) -> WindowSettingsPatch | OpError:
        """Validate raw arguments, or return an ``OpError`` instead of raising."""
        try:
            return cls.model_validate(raw)
        except ValidationError as exc:
            return OpError.from_validation(exc)

    def provided(self) -> dict[str, object]:
        """Return only the fields the caller set, in the display's param shape."""
        return self.model_dump(exclude_none=True)
