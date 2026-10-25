# pyright: reportMissingModuleSource=false
"""WindowSettings -- the display's own window preferences, and how each is applied.

Decoration, opacity, font scale and theme belong to the person at the display: a menu
changes them, a Hub may ask for a theme, and a query reads them back. Each setting is
held here beside the call that makes it true on the live window, so the render loop
neither stores them nor knows how a GLFW attribute or a theme is applied.
"""

from __future__ import annotations

import dataclasses
import logging
from typing import Any, Self, cast, final

from imgui_bundle import hello_imgui

from punt_lux.display.glfw_window import GlfwWindow

logger = logging.getLogger(__name__)

__all__ = ["WindowSettings"]


@dataclasses.dataclass(frozen=True, slots=True)
class _Preferences:
    """What the window is set to now; a change makes a new one."""

    themes: tuple[Any, ...]  # hello_imgui's theme enum members, known once it is up
    decorated: bool
    opacity: float
    font_scale: float
    current_theme: str


@final
class WindowSettings:
    """The window's decoration, opacity, font scale and theme."""

    _prefs: _Preferences
    __slots__ = ("_prefs",)

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._prefs = _Preferences(
            themes=(),
            decorated=True,
            opacity=1.0,
            font_scale=1.1,
            current_theme="imgui_colors_dark",
        )
        return self

    @property
    def themes(self) -> list[Any]:
        """The themes the window offers; none until :meth:`start`."""
        return list(self._prefs.themes)

    @property
    def decorated(self) -> bool:
        """Whether the window has its title bar."""
        return self._prefs.decorated

    @property
    def opacity(self) -> float:
        """The window's opacity, 0.0 transparent to 1.0 opaque."""
        return self._prefs.opacity

    @property
    def font_scale(self) -> float:
        """The scale every font is drawn at."""
        return self._prefs.font_scale

    @property
    def current_theme(self) -> str:
        """The snake_case name of the theme in force."""
        return self._prefs.current_theme

    def window_report(self, **_kwargs: object) -> dict[str, object]:
        """Report opacity, the stored 0.5-3.0 font scale, decoration, and idle rate."""
        return {
            "opacity": self._prefs.opacity,
            "font_scale": self._prefs.font_scale,
            "decorated": self._prefs.decorated,
            "fps_idle": hello_imgui.get_runner_params().fps_idling.fps_idle,
        }

    def theme_report(self, **_kwargs: object) -> dict[str, object]:
        """Report the current theme and the switchable themes as bare names."""
        return {
            "current": self._prefs.current_theme,
            "available": [t.name for t in self._prefs.themes if t.name != "count"],
        }

    def start(self) -> None:
        """Once the window exists: learn its themes, and stop reshows stealing focus.

        GLFW and HelloImGui cannot suppress the one focus grab macOS gives a
        freshly-created process's first show (a documented limit, not a defect this
        call is meant to close); this stops every grab on a respawned display's later
        reshows.
        """
        self._glfw_window().set_focus_on_show(focus=False)
        self._prefs = dataclasses.replace(
            self._prefs, themes=tuple(hello_imgui.ImGuiTheme_)
        )

    def set_decorated(self, decorated: bool) -> None:  # noqa: FBT001
        """Toggle the window's title bar."""
        self._prefs = dataclasses.replace(self._prefs, decorated=decorated)
        self._glfw_window().set_decorated(decorated=decorated)

    def set_opacity(self, opacity: float) -> None:
        """Change the window's opacity."""
        self._prefs = dataclasses.replace(self._prefs, opacity=opacity)
        self._glfw_window().set_opacity(opacity=opacity)

    def set_font_scale(self, scale: float) -> None:
        """Change the scale fonts are drawn at, from the next frame."""
        self._prefs = dataclasses.replace(self._prefs, font_scale=scale)

    def apply_theme(self, theme_name: str) -> None:
        """Apply a theme by snake_case name (e.g. ``imgui_colors_light``)."""
        for theme in self._prefs.themes:
            if theme.name == theme_name:
                hello_imgui.apply_theme(theme)
                self._prefs = dataclasses.replace(self._prefs, current_theme=theme_name)
                return
        logger.warning("Unknown theme %r", theme_name)

    @staticmethod
    def _glfw_window() -> GlfwWindow:
        """Return a control handle to the process's live GLFW window."""
        address = cast(
            "int",
            hello_imgui.get_glfw_window_address(),  # type: ignore[attr-defined]
        )
        return GlfwWindow(address)
