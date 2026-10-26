"""WindowPreferences -- the window settings the display's own menus read and change."""

from __future__ import annotations

from typing import Any, Protocol

__all__ = ["WindowPreferences"]


class WindowPreferences(Protocol):
    """What the Lux menu needs of the window's settings, structurally.

    :class:`~punt_lux.display.window_settings.WindowSettings` is the one real
    implementation; the menu knows only this shape, so it can be built and read
    without a window on screen.
    """

    @property
    def themes(self) -> list[Any]:
        """The themes the window offers."""
        ...

    @property
    def decorated(self) -> bool:
        """Whether the window has its title bar."""
        ...

    @property
    def opacity(self) -> float:
        """The window's opacity, 0.0 transparent to 1.0 opaque."""
        ...

    @property
    def font_scale(self) -> float:
        """The scale every font is drawn at."""
        ...

    def set_decorated(self, *, decorated: bool) -> None:
        """Toggle the window's title bar."""

    def set_opacity(self, opacity: float) -> None:
        """Change the window's opacity."""

    def set_font_scale(self, scale: float) -> None:
        """Change the scale fonts are drawn at."""

    def apply_theme(self, theme_name: str) -> None:
        """Apply a theme by snake_case name."""
