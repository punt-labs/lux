"""Theme name, the current-theme result, and the set-theme request.

``ThemeName`` is the exact set of themes the display's renderer (hello_imgui)
enumerates — the display handler answers with the bare enum name of each, so the
model and the display agree by construction and neither drifts from the other.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from punt_lux.operations.models.common import OpError

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ["SetThemeRequest", "ThemeName", "ThemeState"]

# The display renderer's real theme enumeration (hello_imgui.ImGuiTheme_), minus
# the trailing "count" sentinel. The get_theme handler returns these bare names,
# so this Literal is the display's own set, not a hand-kept parallel list.
ThemeName = Literal[
    "imgui_colors_classic",
    "imgui_colors_dark",
    "imgui_colors_light",
    "material_flat",
    "photoshop_style",
    "gray_variations",
    "gray_variations_darker",
    "microsoft_style",
    "cherry",
    "darcula",
    "darcula_darker",
    "light_rounded",
    "so_dark_accent_blue",
    "so_dark_accent_yellow",
    "so_dark_accent_red",
    "black_is_black",
    "white_is_white",
]


class ThemeState(BaseModel):
    """The active theme and the themes available to switch to."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["ok"] = "ok"
    theme: ThemeName
    available: list[ThemeName]

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> ThemeState | OpError:
        """Build from the display's ``get_theme`` reply, or reject a malformed one.

        The reply names the current theme and enumerates the available ones, both
        as bare theme names; a name the type does not recognize fails validation
        loudly rather than being silently dropped.
        """
        try:
            return cls.model_validate(
                {
                    "theme": payload.get("current"),
                    "available": payload.get("available", []),
                }
            )
        except ValidationError as exc:
            return OpError(code="rejected", reason=OpError.describe(exc.errors()[0]))


class SetThemeRequest(BaseModel):
    """A request to switch the display to a named theme."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    theme: ThemeName

    @classmethod
    def parse(cls, theme: str) -> SetThemeRequest | OpError:
        """Validate the theme name, or return an ``OpError`` instead of raising."""
        try:
            return cls.model_validate({"theme": theme})
        except ValidationError as exc:
            return OpError.from_validation(exc)
