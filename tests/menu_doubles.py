"""Headless doubles for driving the display's menu surfaces without a window.

The menu bar and the World panel both render a ``MenuModel`` through the ImGui
module. ``FakeImGui`` stands in for that module and records every line drawn, so
a test can compare the two surfaces line for line and click any leaf on either.

A label may carry an ImGui id behind ``##`` (``"Lux##world"``); ImGui shows only
the part before it, and so does the recording — what is compared is what the
user reads.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Self, final

from punt_lux.display.menus.wire import WireMenu
from punt_lux.display.menus.wire_field import WireField
from punt_lux.display.replica.frame import Frame
from punt_lux.display.replica.frame_visibility import FrameVisibility
from punt_lux.display.replica.menu_replica import MenuReplica

if TYPE_CHECKING:
    from collections.abc import Collection, Iterable

__all__ = [
    "SEPARATOR",
    "FakeChrome",
    "FakeImGui",
    "FakeTheme",
    "MenuLine",
    "Vec2",
    "checked_menu",
    "ignore",
    "make_frame",
    "make_menu_replica",
    "wire_menu",
]

# The label a separator records under — a rule the user sees between groups.
SEPARATOR = "---"

# Where a background click lands unless a test names somewhere else.
_MIDDLE_OF_THE_WINDOW = (400.0, 300.0)


@dataclass(frozen=True, slots=True)
class MenuLine:
    """One line a surface drew: where it sits, what it reads, and its state."""

    path: tuple[str, ...]
    label: str
    shortcut: str = ""
    checked: bool = False
    enabled: bool = True


@dataclass(frozen=True, slots=True)
class FakeTheme:
    """A theme choice, as hello_imgui's enum members present themselves."""

    name: str


@dataclass(frozen=True, slots=True)
class Vec2:
    """A point, as ImGui reports mouse and viewport coordinates."""

    x: float
    y: float


@dataclass(frozen=True, slots=True)
class Viewport:
    """The main viewport's origin and extent."""

    pos: Vec2
    size: Vec2


@final
class Flag:
    """An ImGui enum member: something with a ``value``."""

    value: int
    __slots__ = ("value",)

    def __new__(cls, value: int) -> Self:
        self = super().__new__(cls)
        self.value = value
        return self


@final
class Cond:
    """ImGui's ``Cond_`` enum, narrowed to the conditions the panel uses."""

    always = Flag(1)
    first_use_ever = Flag(2)


@final
class WindowFlags:
    """ImGui's ``WindowFlags_`` enum, narrowed to the panel's flags."""

    no_collapse = Flag(32)
    always_auto_resize = Flag(64)


@final
class MouseButton:
    """ImGui's ``MouseButton_`` enum."""

    left = Flag(0)


@final
class FakeChrome:
    """A window whose chrome commands only record that they were asked."""

    _top_most: bool
    _asked: list[str]
    __slots__ = ("_asked", "_top_most")

    def __new__(cls, *, top_most: bool = False) -> Self:
        self = super().__new__(cls)
        self._top_most = top_most
        self._asked = []
        return self

    @property
    def asked(self) -> tuple[str, ...]:
        """Return the commands asked of the window, in order."""
        return tuple(self._asked)

    def top_most(self) -> bool:
        """Return whether the window floats above other applications."""
        return self._top_most

    def set_top_most(self, *, on: bool) -> None:
        """Record the requested always-on-top state."""
        self._top_most = on
        self._asked.append(f"set_top_most={on}")

    def reset_size(self) -> None:
        """Record a reset-size request."""
        self._asked.append("reset_size")

    def quit(self) -> None:
        """Record a quit request."""
        self._asked.append("quit")


@final
class FakeImGui:
    """Record the menus a surface draws, in place of the ImGui module.

    *clicks* names the item labels the user is clicking this frame; every other
    item reports untouched. *menus_open* False makes every menu report closed,
    the state ImGui is in until the user opens a menu.
    """

    Cond_ = Cond
    WindowFlags_ = WindowFlags
    MouseButton_ = MouseButton

    _clicks: frozenset[str]
    _menus_open: bool
    _lines: list[MenuLine]
    _path: list[str]
    _windows: list[str]
    _open_windows: int
    _close_button: bool
    _mouse_clicked: bool
    _mouse_pos: Vec2
    _item_hovered: bool
    _window_hovered: bool
    __slots__ = (
        "_clicks",
        "_close_button",
        "_item_hovered",
        "_lines",
        "_menus_open",
        "_mouse_clicked",
        "_mouse_pos",
        "_open_windows",
        "_path",
        "_window_hovered",
        "_windows",
    )

    def __new__(cls, clicks: Collection[str] = (), *, menus_open: bool = True) -> Self:
        self = super().__new__(cls)
        self._clicks = frozenset(clicks)
        self._menus_open = menus_open
        self._lines = []
        self._path = []
        self._windows = []
        self._open_windows = 0
        self._close_button = False
        self._mouse_clicked = False
        self._mouse_pos = Vec2(0.0, 0.0)
        self._item_hovered = False
        self._window_hovered = True
        return self

    # -- what was drawn -----------------------------------------------------

    @property
    def lines(self) -> tuple[MenuLine, ...]:
        """Return every line drawn this frame, in order."""
        return tuple(self._lines)

    @property
    def windows(self) -> tuple[str, ...]:
        """Return the titles of the windows opened this frame."""
        return tuple(self._windows)

    @property
    def open_windows(self) -> int:
        """Return how many windows are still on the stack — 0 when balanced."""
        return self._open_windows

    def labels_under(self, *path: str) -> tuple[str, ...]:
        """Return the labels drawn directly under *path*."""
        return tuple(line.label for line in self._lines if line.path == path)

    def line(self, label: str) -> MenuLine:
        """Return the single line reading *label*, or raise if it is not there."""
        found = [line for line in self._lines if line.label == label]
        if len(found) != 1:
            msg = f"expected exactly one line labeled {label!r}, drew {len(found)}"
            raise AssertionError(msg)
        return found[0]

    # -- the ImGui surface the menus call -----------------------------------

    def begin_menu(self, label: str) -> bool:
        """Open a menu, recording it as a line of its parent.

        A shut menu records its own line and grows no path: production skips
        ``end_menu`` when this returns False, so pushing here would leave the
        next sibling recorded as a child.
        """
        visible = self._visible(label)
        self._lines.append(MenuLine(tuple(self._path), visible))
        if not self._menus_open:
            return False
        self._path.append(visible)
        return True

    def end_menu(self) -> None:
        """Close the innermost open menu."""
        self._path.pop()

    def menu_item(
        self,
        label: str,
        shortcut: str = "",
        checked: bool = False,
        enabled: bool = True,
    ) -> tuple[bool, bool]:
        """Record an item and report whether the user clicked it.

        A disabled item never reports a click: ImGui does not activate one, so
        neither may this double.
        """
        visible = self._visible(label)
        self._lines.append(
            MenuLine(tuple(self._path), visible, shortcut, checked, enabled)
        )
        clicked = enabled and visible in self._clicks
        return clicked, checked != clicked

    def separator(self) -> None:
        """Record a rule between groups."""
        self._lines.append(MenuLine(tuple(self._path), SEPARATOR, enabled=False))

    def begin(self, name: str, p_open: bool, _flags: int) -> tuple[bool, bool]:
        """Open a window, recording its title and its place on the stack."""
        self._windows.append(self._visible(name))
        self._open_windows += 1
        return True, p_open and not self._close_button

    def end(self) -> None:
        """Close the current window, taking it off the stack."""
        self._open_windows -= 1

    def small_button(self, _label: str) -> bool:
        """Report a button the user did not press."""
        return False

    def set_next_window_size(self, _size: Any, _cond: int) -> None:
        """Accept the panel's requested size."""

    def set_next_window_pos(self, _pos: Any, _cond: int) -> None:
        """Accept the panel's requested position."""

    def is_mouse_clicked(self, _button: Flag) -> bool:
        """Report whether the left button went down, and consume the click.

        A click is an edge, not a state: ImGui reports it for one frame only,
        so an armed click must not read as a fresh click on the next one.
        """
        clicked = self._mouse_clicked
        self._mouse_clicked = False
        return clicked

    def is_any_item_hovered(self) -> bool:
        """Report whether the mouse is over a widget."""
        return self._item_hovered

    def is_window_hovered(self) -> bool:
        """Report whether the mouse is over the current window."""
        return self._window_hovered

    def get_mouse_pos(self) -> Vec2:
        """Return where the mouse is."""
        return self._mouse_pos

    def get_main_viewport(self) -> Viewport:
        """Return a 1200x800 viewport at the origin."""
        return Viewport(Vec2(0.0, 0.0), Vec2(1200.0, 800.0))

    # -- driving the user ---------------------------------------------------

    def click_background(self, pos: Vec2 | None = None) -> None:
        """Arm a left click on the window background at *pos*."""
        self._mouse_clicked = True
        self._mouse_pos = pos if pos is not None else Vec2(*_MIDDLE_OF_THE_WINDOW)
        self._item_hovered = False
        self._window_hovered = True

    def click_widget(self) -> None:
        """Arm a left click that lands on a widget rather than the background."""
        self._mouse_clicked = True
        self._item_hovered = True

    def click_close_button(self) -> None:
        """Arm the window's own close button — ImGui answers through ``begin``."""
        self._close_button = True

    @staticmethod
    def _visible(label: str) -> str:
        """Return the part of *label* ImGui shows — everything before ``##``."""
        return label.split("##")[0]


def ignore(*_args: object) -> None:
    """Accept whatever the display reports and do nothing with it."""


def make_menu_replica(**overrides: Any) -> MenuReplica:
    """Build a MenuReplica whose collaborators are all doubles."""
    defaults: dict[str, Any] = {
        "emit_event": ignore,
        "on_theme_selected": ignore,
        "on_decorated_toggled": ignore,
        "on_opacity_changed": ignore,
        "on_font_scale_changed": ignore,
        "get_themes": list,
        "get_decorated": lambda: True,
        "get_opacity": lambda: 1.0,
        "get_font_scale": lambda: 1.0,
        "get_frames": dict,
        "on_clear_all": ignore,
        "on_fit_all": ignore,
        "on_raise_frame": ignore,
        "chrome": FakeChrome(),
    }
    defaults.update(overrides)
    return MenuReplica(**defaults)


def wire_menu(label: str, items: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Return a replicated menu payload in the shape the Hub sends."""
    return {"label": label, "items": list(items)}


def checked_menu(payload: dict[str, Any]) -> WireMenu:
    """Return the menu a payload describes, checked as the display checks it.

    Raises if the payload is malformed, which is what the display's boundary
    does before it logs the rejection — a test that wants a menu gets a menu or
    a failure, never a half-formed one.
    """
    return WireMenu.of_payload(payload, field=WireField("test"))


def make_frame(
    frame_id: str,
    *,
    visibility: FrameVisibility = FrameVisibility.ON_SCREEN,
    title: str | None = None,
) -> Frame:
    """Return an empty frame in the visibility named, on screen by default."""
    return Frame(
        frame_id=frame_id,
        title=title if title is not None else frame_id,
        owner_fds=set(),
        scenes={},
        scene_order=[],
        visibility=visibility,
    )
