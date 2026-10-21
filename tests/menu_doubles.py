"""Headless doubles for driving the display's menu surfaces without a window.

The menu bar and the World panel both render a ``MenuModel`` through the ImGui
module. ``FakeImGui`` stands in for that module and records every line drawn, so
a test can compare the two surfaces line for line and click any leaf on either.

A label may carry an ImGui id behind ``##`` (``"Lux##world"``); ImGui shows only
the part before it, and so does the recording — what is compared is what the
user reads.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, Self, final

from punt_lux.display.menus.own_menus import OwnMenus
from punt_lux.display.menus.wire import WireMenu
from punt_lux.display.menus.wire_field import WireField
from punt_lux.display.replica.frame import Frame
from punt_lux.display.replica.frame_visibility import FrameVisibility
from punt_lux.display.replica.menu_replica import MenuReplica
from punt_lux.domain.identity import HubId

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

# Where the fake window's content starts, in screen coordinates.
_CURSOR_START = (108.0, 108.0)

# Pixels per character in the fake's text measurement.
_CHAR_WIDTH = 8.0

# Where a background click lands unless a test names somewhere else.
_MIDDLE_OF_THE_WINDOW = (400.0, 300.0)


@dataclass(frozen=True, slots=True)
class MenuLine:
    """One line a surface drew: where it sits, what it reads, and its state.

    ``label`` is what the user reads (before any ``##``); ``raw`` is the full
    string ImGui identifies the widget by (label plus the hidden id salt).
    """

    path: tuple[str, ...]
    label: str
    shortcut: str = ""
    checked: bool = False
    enabled: bool = True
    # Diagnostic only: two surfaces show one menu with different ids (id_suffix),
    # so raw is excluded from equality -- equality models visible sameness.
    raw: str = field(default="", compare=False)


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
class FakeIO:
    """ImGui's ``io``, narrowed to the drag-distance fields the glyph reads."""

    mouse_drag_threshold = 6.0
    mouse_drag_max_distance_sqr = (0.0, 0.0, 0.0, 0.0, 0.0)


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
class HoveredFlags:
    """ImGui's ``HoveredFlags_`` enum, narrowed to the glyph's flags."""

    allow_when_blocked_by_popup = Flag(8)
    allow_when_blocked_by_active_item = Flag(32)


@final
class MouseButton:
    """ImGui's ``MouseButton_`` enum."""

    left = Flag(0)


@final
class Col:
    """ImGui's ``Col_`` enum, narrowed to the title-bar glyph's colors."""

    button = Flag(21)
    button_hovered = Flag(22)
    text = Flag(0)


@final
class FakeStyle:
    """ImGui's style, narrowed to what the info popup's header reads."""

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    @property
    def item_spacing(self) -> Vec2:
        """Return the gap ImGui leaves between items on a line."""
        return Vec2(8.0, 4.0)

    @property
    def frame_padding(self) -> Vec2:
        """Return the padding ImGui puts inside a button around its label."""
        return Vec2(4.0, 3.0)

    def color_(self, _which: Flag) -> Vec2:
        """Return a style color; the value is unused by the recording double."""
        return Vec2(0.0, 0.0)


@final
class FakeDrawList:
    """A draw list whose primitive calls only need to be accepted."""

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    def add_rect_filled(
        self, _low: Vec2, _high: Vec2, _color: int, _rounding: float = 0.0
    ) -> None:
        """Accept a filled-rect request."""

    def add_text(self, _pos: Vec2, _color: int, _text: str) -> None:
        """Accept a text-draw request."""

    def push_clip_rect(
        self, _low: Vec2, _high: Vec2, *, intersect_with_current_clip_rect: bool
    ) -> None:
        """Accept a clip-rect push."""

    def pop_clip_rect(self) -> None:
        """Accept a clip-rect pop."""


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
    HoveredFlags_ = HoveredFlags
    Col_ = Col

    _clicks: frozenset[str]
    _menus_open: bool
    _strict_ids: bool
    _seen_ids: dict[tuple[str, ...], set[str]]
    _lines: list[MenuLine]
    _path: list[str]
    _windows: list[str]
    _open_windows: int
    _close_button: bool
    _mouse_clicked: bool
    _mouse_released: bool
    _mouse_pos: Vec2
    _item_hovered: bool
    _window_hovered: bool
    _table_rows: list[tuple[str, ...]]
    _same_lines: list[tuple[float, float]]
    _cursor: Vec2
    _max_x: float
    _table_right: float
    _close_buttons: dict[int, Vec2]
    _ids: dict[int, str]
    _current_row: list[str]
    _in_table: bool
    _focus_requests: int
    _open_popups: set[str]
    _opened_popup_ids: list[str]
    _rendered_popups: list[str]
    _current_popup: str | None
    __slots__ = (
        "_clicks",
        "_close_button",
        "_close_buttons",
        "_current_popup",
        "_current_row",
        "_cursor",
        "_focus_requests",
        "_ids",
        "_in_table",
        "_item_hovered",
        "_lines",
        "_max_x",
        "_menus_open",
        "_mouse_clicked",
        "_mouse_pos",
        "_mouse_released",
        "_open_popups",
        "_open_windows",
        "_opened_popup_ids",
        "_path",
        "_rendered_popups",
        "_same_lines",
        "_seen_ids",
        "_strict_ids",
        "_table_right",
        "_table_rows",
        "_window_hovered",
        "_windows",
    )

    def __new__(
        cls,
        clicks: Collection[str] = (),
        *,
        menus_open: bool = True,
        strict_ids: bool = False,
        table_right: float = 0.0,
    ) -> Self:
        self = super().__new__(cls)
        self._clicks = frozenset(clicks)
        self._menus_open = menus_open
        self._strict_ids = strict_ids
        self._seen_ids = {}
        self._lines = []
        self._path = []
        self._windows = []
        self._open_windows = 0
        self._close_button = False
        self._mouse_clicked = False
        self._mouse_released = False
        self._mouse_pos = Vec2(0.0, 0.0)
        self._item_hovered = False
        self._window_hovered = True
        self._table_rows = []
        self._same_lines = []
        self._cursor = Vec2(*_CURSOR_START)
        self._max_x = 0.0
        self._table_right = table_right
        self._close_buttons = {}
        self._ids = {}
        self._current_row = []
        self._in_table = False
        self._focus_requests = 0
        self._open_popups = set()
        self._opened_popup_ids = []
        self._rendered_popups = []
        self._current_popup = None
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

    @property
    def table_rows(self) -> tuple[tuple[str, ...], ...]:
        """Return every row drawn by ``begin_table``/``table_next_row``, in order."""
        return tuple(self._table_rows)

    def labels_under(self, *path: str) -> tuple[str, ...]:
        """Return the labels drawn directly under *path*."""
        return tuple(line.label for line in self._lines if line.path == path)

    def raw_ids_under(self, *path: str) -> tuple[str, ...]:
        """Return the full ImGui id strings drawn directly under *path*."""
        return tuple(line.raw for line in self._lines if line.path == path)

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
        self._note_id(label)
        self._lines.append(MenuLine(tuple(self._path), visible, raw=label))
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
        self._note_id(label)
        self._lines.append(
            MenuLine(tuple(self._path), visible, shortcut, checked, enabled, raw=label)
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

    def small_button(self, label: str) -> bool:
        """Report whether the user clicked this button, by its visible label."""
        return self._visible(label) in self._clicks

    def set_next_window_size(self, _size: Any, _cond: int) -> None:
        """Accept the panel's requested size."""

    def set_next_window_pos(self, _pos: Any, _cond: int) -> None:
        """Accept the panel's requested position."""

    def set_next_window_focus(self) -> None:
        """Record a request to raise the next window to the front."""
        self._focus_requests += 1

    @property
    def focus_requests(self) -> int:
        """Return how many times a window was asked to the front this fixture."""
        return self._focus_requests

    def open_popup(self, popup_id: str) -> None:
        """Mark a popup-stack id as open, recording the request in order."""
        self._open_popups.add(popup_id)
        self._opened_popup_ids.append(popup_id)

    def begin_popup(self, popup_id: str, _flags: int = 0) -> bool:
        """Draw a popup-layer window while its id is open; record it if so.

        Returns False for an id that was never opened (or has been dismissed),
        exactly as ImGui does — the caller must skip ``end_popup`` in that case.
        """
        if popup_id not in self._open_popups:
            return False
        self._rendered_popups.append(popup_id)
        self._open_windows += 1
        self._current_popup = popup_id
        return True

    def close_current_popup(self) -> None:
        """Dismiss the popup ImGui currently has open — the close button's call.

        The next ``begin_popup`` for that id reports it shut, as real ImGui does
        once a popup calls ``close_current_popup`` from inside its own body.
        """
        if self._current_popup is not None:
            self._open_popups.discard(self._current_popup)

    def end_popup(self) -> None:
        """Close the current popup, taking it off the stack."""
        self._open_windows -= 1
        self._current_popup = None

    @property
    def opened_popup_ids(self) -> tuple[str, ...]:
        """Return the ids ``open_popup`` was asked to open, in order."""
        return tuple(self._opened_popup_ids)

    @property
    def popups(self) -> tuple[str, ...]:
        """Return the popup ids ``begin_popup`` drew this fixture, in order."""
        return tuple(self._rendered_popups)

    ImVec2 = Vec2

    def set_cursor_screen_pos(self, pos: Vec2) -> None:
        """Move the cursor, as the next item will be drawn from there."""
        self._cursor = pos

    def get_cursor_screen_pos(self) -> Vec2:
        """Return where the next item will be drawn."""
        return self._cursor

    @property
    def internal(self) -> SimpleNamespace:
        """Return the internal API narrowed to the window's widest extent so far."""
        window = SimpleNamespace(
            dc=SimpleNamespace(cursor_max_pos=Vec2(self._max_x, self._cursor.y))
        )
        return SimpleNamespace(
            get_current_window_read=lambda: window,
            close_button=self._native_close_button,
        )

    def get_id(self, label: str) -> int:
        """Return a stable id for *label*, remembering which label it was."""
        value = len(label) * 7919 + sum(map(ord, label))
        self._ids[value] = label
        return value

    def get_font_size(self) -> float:
        """Return the font size: the side of ImGui's close button."""
        return 12.0

    def get_text_line_height(self) -> float:
        """Return a text line's height, taller than the font so a centre shows."""
        return 16.0

    def dummy(self, size: Vec2) -> None:
        """Reserve *size* at the cursor, as ImGui does: widen, then advance."""
        self._max_x = max(self._max_x, self._cursor.x + size.x)
        self._cursor = Vec2(self._cursor.x, self._cursor.y + size.y)

    def _native_close_button(self, button_id: int, pos: Vec2) -> bool:
        """Record where ImGui's native close button was drawn; report a click."""
        self._close_buttons[button_id] = pos
        return self._ids[button_id] in self._clicks

    def close_button_pos(self, label: str) -> Vec2:
        """Return where the native close button with id *label* was drawn."""
        return self._close_buttons[self.get_id(label)]

    def get_window_pos(self) -> Vec2:
        """Return a fixed window origin."""
        return Vec2(100.0, 100.0)

    def get_window_size(self) -> Vec2:
        """Return a fixed window extent."""
        return Vec2(400.0, 300.0)

    def get_frame_height(self) -> float:
        """Return a fixed title-bar/button height."""
        return 20.0

    def get_item_rect_min(self) -> Vec2:
        """Return the last-drawn item's top-left corner, as a fixed anchor."""
        return Vec2(370.0, 100.0)

    def begin_table(self, _id: str, _columns: int) -> bool:
        """Open a table; every call succeeds."""
        self._in_table = True
        return True

    def table_next_row(self) -> None:
        """Flush the current row and start a new one."""
        if self._current_row:
            self._table_rows.append(tuple(self._current_row))
            self._current_row = []

    def table_next_column(self) -> None:
        """Advance to the next column; ``text`` fills it."""

    def text(self, value: str) -> None:
        """Record one cell's text, but only inside a table.

        A ``text`` drawn outside a table — the popup header's title — is a plain
        line, not a table cell, so it must not leak into the recorded rows.
        """
        if self._in_table:
            self._current_row.append(value)
        else:
            self._max_x = max(
                self._max_x, self._cursor.x + self.calc_text_size(value).x
            )

    def end_table(self) -> None:
        """Close the table, flushing any row still open."""
        if self._current_row:
            self._table_rows.append(tuple(self._current_row))
            self._current_row = []
        self._in_table = False
        self._max_x = max(self._max_x, self._table_right)

    def same_line(self, offset: float = 0.0, spacing: float = -1.0) -> None:
        """Record a same-line request as (offset from the start, spacing)."""
        self._same_lines.append((offset, spacing))

    @property
    def same_lines(self) -> tuple[tuple[float, float], ...]:
        """Every same-line request so far, as (offset from the start, spacing)."""
        return tuple(self._same_lines)

    def get_style(self) -> FakeStyle:
        """Return the style the header reads for its item spacing."""
        return FakeStyle()

    def calc_text_size(self, text: str) -> Vec2:
        """Return a fixed-pitch text extent: a character is 8 px wide, 12 high."""
        return Vec2(_CHAR_WIDTH * len(text), 12.0)

    def get_window_draw_list(self) -> FakeDrawList:
        """Return the draw list the title-bar glyph paints onto."""
        return FakeDrawList()

    def get_color_u32(self, _color: Any) -> int:
        """Return a packed color; the value is unused by the recording double."""
        return 0

    def is_mouse_clicked(self, _button: Flag) -> bool:
        """Report whether the left button went down, and consume the click.

        A click is an edge, not a state: ImGui reports it for one frame only,
        so an armed click must not read as a fresh click on the next one.
        """
        clicked = self._mouse_clicked
        self._mouse_clicked = False
        return clicked

    def is_mouse_released(self, _button: Flag) -> bool:
        """Report whether an armed click completed, consuming it like a click.

        The double models a click as one atomic press-and-release, so the armed
        click is both the press edge and the release edge -- each consumed
        independently, so reading one does not hide the other.
        """
        released = self._mouse_released
        self._mouse_released = False
        return released

    @staticmethod
    def get_io() -> FakeIO:
        """Return an io reporting no drag: an armed click never moves the mouse."""
        return FakeIO()

    def is_any_item_hovered(self) -> bool:
        """Report whether the mouse is over a widget."""
        return self._item_hovered

    def is_window_hovered(self, _flags: int = 0) -> bool:
        """Report whether the mouse is over the current window."""
        return self._window_hovered

    @staticmethod
    def get_current_context() -> SimpleNamespace:
        """Return a context whose hovered window is never a popup."""
        return SimpleNamespace(hovered_window=None)

    def occlude_window(self) -> None:
        """Put another window in front of the current one, under the mouse."""
        self._window_hovered = False

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
        self._mouse_released = True
        self._mouse_pos = pos if pos is not None else Vec2(*_MIDDLE_OF_THE_WINDOW)
        self._item_hovered = False
        self._window_hovered = True

    def click_widget(self) -> None:
        """Arm a left click that lands on a widget rather than the background."""
        self._mouse_clicked = True
        self._mouse_released = True
        self._item_hovered = True

    def click_close_button(self) -> None:
        """Arm the window's own close button — ImGui answers through ``begin``."""
        self._close_button = True

    def click_at(self, pos: Vec2) -> None:
        """Arm a left click at *pos* — for hit-testing a hand-painted glyph."""
        self._mouse_clicked = True
        self._mouse_released = True
        self._mouse_pos = pos

    def press_at(self, pos: Vec2) -> None:
        """Arm only the press edge of a left click at *pos* -- no release yet."""
        self._mouse_clicked = True
        self._mouse_released = False
        self._mouse_pos = pos

    def release_at(self, pos: Vec2) -> None:
        """Arm only the release edge of a left click at *pos* -- no new press."""
        self._mouse_clicked = False
        self._mouse_released = True
        self._mouse_pos = pos

    def dismiss_popup(self, popup_id: str) -> None:
        """Simulate ImGui's own dismissal of a popup — an outside click/Escape.

        The next ``begin_popup`` for *popup_id* reports it shut, as real ImGui
        does once the user clicks away from a non-modal popup.
        """
        self._open_popups.discard(popup_id)

    def _note_id(self, label: str) -> None:
        """Record *label*'s ImGui id, raising on a conflict under strict mode.

        Real ImGui raises "N visible items with conflicting ID" when two
        widgets share an id within one scope. In strict mode this double
        reproduces that on the *effective* id ImGui hashes, scoped by the
        current menu path.
        """
        if not self._strict_ids:
            return
        scope = tuple(self._path)
        seen = self._seen_ids.setdefault(scope, set())
        ident = self._effective_id(label)
        if ident in seen:
            msg = f"conflicting ImGui id {ident!r} (from {label!r}) under {scope}"
            raise AssertionError(msg)
        seen.add(ident)

    @staticmethod
    def _effective_id(label: str) -> str:
        """Return the id ImGui hashes for *label*.

        ImGui's ``###`` marker resets the id to the text following the last
        ``###`` -- the display prefix contributes nothing -- so an unguarded
        ``###`` in an id salt would drop everything before it (e.g. the Hub
        token). A plain ``##`` is only a display/id split, so the whole string
        still seeds the id.
        """
        return label.rsplit("###", 1)[1] if "###" in label else label

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
    emit_event = defaults.pop("emit_event")
    return MenuReplica(
        emit_event=emit_event,
        on_raise_frame=defaults["on_raise_frame"],
        get_frames=defaults["get_frames"],
        own=OwnMenus(**defaults),
    )


def wire_menu(
    label: str, items: Iterable[dict[str, Any]], owner: str | None = None
) -> dict[str, Any]:
    """Return a replicated menu payload in the shape the Hub sends.

    ``owner`` is the owning-session id the Hub stamps onto an agent bar menu so
    the display keys its heading per session; omit it for an owner-less menu.
    """
    payload: dict[str, Any] = {"label": label, "items": list(items)}
    if owner is not None:
        payload["owner"] = owner
    return payload


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
    hub: HubId | None = None,
) -> Frame:
    """Return an empty frame in the visibility named, on screen by default."""
    return Frame(
        hub=hub if hub is not None else HubId.stub(),
        frame_id=frame_id,
        title=title if title is not None else frame_id,
        owner_fds=set(),
        scenes={},
        scene_order=[],
        visibility=visibility,
    )
