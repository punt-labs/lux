"""Theme name, the current-theme result, and the set-theme request."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, cast, get_args

from pydantic import BaseModel, ConfigDict, ValidationError

from punt_lux.operations.models.common import OpError

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ["SetThemeRequest", "ThemeName", "ThemeState"]

ThemeName = Literal[
    "imgui_colors_light",
    "imgui_colors_dark",
    "imgui_colors_classic",
    "darcula",
    "darcula_darker",
    "material_flat",
    "photoshop_style",
    "grey_flat",
    "cherry",
    "light_rounded",
    "microsoft_style",
    "from_imgui_colors_dark",
]

_KNOWN_THEMES: frozenset[str] = frozenset(get_args(ThemeName))


class ThemeState(BaseModel):
    """The active theme and the themes available to switch to."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["ok"] = "ok"
    theme: ThemeName
    available: list[ThemeName]

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> ThemeState | OpError:
        """Build from the display's ``get_theme`` reply.

        The reply names the current theme and enumerates the available ones. The
        available list is normalized to bare theme names — the display enumerates
        them as qualified enum strings — and narrowed to the known set, so an
        entry the type does not recognize is dropped rather than rejecting the
        whole reply.
        """
        current = cls._bare_name(payload.get("theme", payload.get("current")))
        if current not in _KNOWN_THEMES:
            return OpError(code="rejected", reason=f"unknown theme: {current!r}")
        raw = payload.get("available", [])
        entries = cast("list[object]", raw) if isinstance(raw, list) else []
        available = [
            name
            for entry in entries
            if (name := cls._bare_name(entry)) in _KNOWN_THEMES
        ]
        return cls.model_validate({"theme": current, "available": available})

    @staticmethod
    def _bare_name(value: object) -> str:
        """Return the trailing segment of a possibly-qualified enum string."""
        return str(value).rsplit(".", maxsplit=1)[-1]


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
