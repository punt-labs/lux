"""The menus the display owns: Lux, Windows, and Help.

These are the display's own commands — the theme, the window, the frames, the
version it is running — as against the menus the Hub replicates to it. They are
built here rather than in the manager so that holding replicated state and
offering the display's own commands are two objects with one job each: this one
knows nothing about the Hub, and the manager knows nothing about opacity presets.

Every item reads live state at the moment the menu is composed, so a preset shows
as in effect, and a frame command goes dim, according to how the display is right
now rather than how it was when the manager was built.

``imgui`` is typed ``Any``: imgui_bundle ships no type stubs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Self, final

from punt_lux import __version__
from punt_lux.display.menus.entries import MenuItem, MenuSeparator
from punt_lux.display.menus.model import Submenu

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from punt_lux.display.window_chrome import WindowChromeCommands
    from punt_lux.scene.frame import Frame

__all__ = ["OwnMenus"]

_FONT_STEP = 0.1
_FONT_MIN = 0.5
_FONT_MAX = 3.0
_OPACITY_PRESETS = (25, 50, 75, 100)
# An opacity preset reads as the current one when it is within half a step.
_OPACITY_MATCH = 0.05


@final
class OwnMenus:
    """Build the display's own menus from the state and commands it is given.

    Receives callbacks for user selections (theme, opacity, and the rest) but
    does not own the state those callbacks mutate.
    """

    _on_theme_selected: Callable[[str], None]
    _on_decorated_toggled: Callable[[bool], None]
    _on_opacity_changed: Callable[[float], None]
    _on_font_scale_changed: Callable[[float], None]
    _get_themes: Callable[[], list[Any]]
    _get_decorated: Callable[[], bool]
    _get_opacity: Callable[[], float]
    _get_font_scale: Callable[[], float]
    _get_frames: Callable[[], Mapping[str, Frame]]
    _on_clear_all: Callable[[], None]
    _on_fit_all: Callable[[], None]
    _chrome: WindowChromeCommands
    __slots__ = (
        "_chrome",
        "_get_decorated",
        "_get_font_scale",
        "_get_frames",
        "_get_opacity",
        "_get_themes",
        "_on_clear_all",
        "_on_decorated_toggled",
        "_on_fit_all",
        "_on_font_scale_changed",
        "_on_opacity_changed",
        "_on_theme_selected",
    )

    def __new__(
        cls,
        *,
        on_theme_selected: Callable[[str], None],
        on_decorated_toggled: Callable[[bool], None],
        on_opacity_changed: Callable[[float], None],
        on_font_scale_changed: Callable[[float], None],
        get_themes: Callable[[], list[Any]],
        get_decorated: Callable[[], bool],
        get_opacity: Callable[[], float],
        get_font_scale: Callable[[], float],
        get_frames: Callable[[], Mapping[str, Frame]],
        on_clear_all: Callable[[], None],
        on_fit_all: Callable[[], None],
        chrome: WindowChromeCommands,
    ) -> Self:
        self = super().__new__(cls)
        self._on_theme_selected = on_theme_selected
        self._on_decorated_toggled = on_decorated_toggled
        self._on_opacity_changed = on_opacity_changed
        self._on_font_scale_changed = on_font_scale_changed
        self._get_themes = get_themes
        self._get_decorated = get_decorated
        self._get_opacity = get_opacity
        self._get_font_scale = get_font_scale
        self._get_frames = get_frames
        self._on_clear_all = on_clear_all
        self._on_fit_all = on_fit_all
        self._chrome = chrome
        return self

    def sections(self) -> list[Submenu]:
        """Return the display's own menus, in the order they appear on the bar."""
        return [self._lux_menu(), self._windows_menu(), self._help_menu()]

    def _lux_menu(self) -> Submenu:
        """Build the Lux menu: settings, font size, quit."""
        return Submenu(
            "Lux",
            [
                self._settings_menu(),
                MenuSeparator(),
                MenuItem("Increase Font", lambda: self._step_font(_FONT_STEP)),
                MenuItem("Decrease Font", lambda: self._step_font(-_FONT_STEP)),
                MenuSeparator(),
                MenuItem("Quit", self._chrome.quit, shortcut="Cmd+Q"),
            ],
        )

    def _settings_menu(self) -> Submenu:
        """Build the Settings submenu: theme, window chrome, opacity."""
        decorated = self._get_decorated()
        return Submenu(
            "Settings",
            [
                self._theme_menu(),
                MenuSeparator(),
                MenuItem.toggle(
                    "Always on Top",
                    self._toggle_top_most,
                    checked=self._chrome.top_most(),
                ),
                MenuItem.toggle(
                    "Borderless",
                    lambda: self._on_decorated_toggled(not decorated),
                    checked=not decorated,
                ),
                MenuSeparator(),
                self._opacity_menu(),
            ],
        )

    def _theme_menu(self) -> Submenu:
        """Build the theme picker from the themes the display offers."""
        return Submenu("Theme", [self._theme_item(t) for t in self._get_themes()])

    def _theme_item(self, theme: Any) -> MenuItem:
        """Build one theme choice; selecting it applies that theme."""
        name = str(theme.name)
        return MenuItem(
            name.replace("_", " ").title(), lambda: self._on_theme_selected(name)
        )

    def _opacity_menu(self) -> Submenu:
        """Build the opacity presets, checking the one in effect."""
        return Submenu("Opacity", [self._opacity_item(p) for p in _OPACITY_PRESETS])

    def _opacity_item(self, percent: int) -> MenuItem:
        """Build one opacity preset; selecting it applies that opacity."""
        value = percent / 100.0
        in_effect = abs(self._get_opacity() - value) < _OPACITY_MATCH
        return MenuItem.toggle(
            f"{percent}%", lambda: self._on_opacity_changed(value), checked=in_effect
        )

    def _windows_menu(self) -> Submenu:
        """Build the Windows menu: frame layout, then window chrome."""
        frames = self._get_frames().values()
        expanded = any(not frame.minimized for frame in frames)
        minimized = any(frame.minimized for frame in frames)
        return Submenu(
            "Windows",
            [
                MenuItem(
                    "Collapse All",
                    lambda: self._minimize_all(minimized=True),
                    enabled=expanded,
                ),
                MenuItem(
                    "Expand All",
                    lambda: self._minimize_all(minimized=False),
                    enabled=minimized,
                ),
                MenuItem("Fit All", self._on_fit_all, enabled=bool(frames)),
                MenuSeparator(),
                MenuItem("Clear All", self._on_clear_all),
                MenuItem("Reset Size", self._chrome.reset_size),
            ],
        )

    def _help_menu(self) -> Submenu:
        """Build the Help menu: the running version, as a line to read."""
        return Submenu("Help", [MenuItem.caption(f"Lux v{__version__}")])

    def _step_font(self, delta: float) -> None:
        """Step the font scale by *delta*, held inside the supported range."""
        scale = round(self._get_font_scale() + delta, 1)
        self._on_font_scale_changed(min(max(scale, _FONT_MIN), _FONT_MAX))

    def _toggle_top_most(self) -> None:
        """Flip whether the window floats above other applications."""
        self._chrome.set_top_most(on=not self._chrome.top_most())

    def _minimize_all(self, *, minimized: bool) -> None:
        """Minimize every frame, or restore every frame."""
        for frame in self._get_frames().values():
            frame.minimized = minimized
