"""Window settings — the current-settings result and the change request."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from punt_lux.operations.models.common import OpError

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ["WindowSettings", "WindowSettingsPatch"]


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
            return OpError(code="rejected", reason=OpError.describe(exc.errors()[0]))


class WindowSettingsPatch(BaseModel):
    """Only the provided fields change; a ``None`` field is left untouched."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    opacity: float | None = None  # None leaves the window opacity unchanged
    font_scale: float | None = None  # None leaves the font scale unchanged
    decorated: bool | None = None  # None leaves the decoration unchanged
    fps_idle: float | None = None  # None leaves the idle frame rate unchanged

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
