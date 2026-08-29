"""The Windows menu: where every frame is, and the commands that move it.

Split out of :class:`~punt_lux.display.menus.own_menus.OwnMenus` because the
frames are a concern of their own. That class knows about themes, opacity and
font size — none of which has anything to say about where a window sits — and
this one knows about nothing else.

Every entry reads live state at the moment the menu is composed, so a command
goes dim according to how the workspace is right now: Collapse All wants
something on screen to send away, Expand All wants something away to bring back.

The closed-frame entries at the bottom are the only way back for a frame whose
client owns no menu of its own. A closed frame deliberately carries no dock
pill — that is what makes closing a stronger statement than collapsing — so
without these, an ordinary ``show()`` scene's close button would be a one-way
door (DES-065 R8, finding F3).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.display.menus.entries import MenuItem, MenuSeparator
from punt_lux.display.menus.model import Submenu

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from punt_lux.display.replica.frame import Frame
    from punt_lux.display.window_chrome import WindowChromeCommands

__all__ = ["WindowsMenu"]


@final
class WindowsMenu:
    """Compose the Windows menu from the frames the display is holding."""

    _get_frames: Callable[[], Mapping[str, Frame]]
    _on_clear_all: Callable[[], None]
    _on_fit_all: Callable[[], None]
    _on_raise_frame: Callable[[str], None]
    _chrome: WindowChromeCommands
    __slots__ = (
        "_chrome",
        "_get_frames",
        "_on_clear_all",
        "_on_fit_all",
        "_on_raise_frame",
    )

    def __new__(
        cls,
        *,
        get_frames: Callable[[], Mapping[str, Frame]],
        on_clear_all: Callable[[], None],
        on_fit_all: Callable[[], None],
        on_raise_frame: Callable[[str], None],
        chrome: WindowChromeCommands,
    ) -> Self:
        self = super().__new__(cls)
        self._get_frames = get_frames
        self._on_clear_all = on_clear_all
        self._on_fit_all = on_fit_all
        self._on_raise_frame = on_raise_frame
        self._chrome = chrome
        return self

    def section(self) -> Submenu:
        """Build the menu: frame layout, the closed frames, then window chrome."""
        frames = list(self._get_frames().values())
        return Submenu(
            "Windows",
            [
                *self._layout_items(frames),
                *self._closed_entries(frames),
                MenuSeparator(),
                MenuItem("Clear All", self._on_clear_all),
                MenuItem("Reset Size", self._chrome.reset_size),
            ],
        )

    def _layout_items(self, frames: list[Frame]) -> list[MenuItem]:
        """Build the three bulk-layout commands, each dim when it has no work."""
        return [
            MenuItem(
                "Collapse All",
                self._collapse_all,
                enabled=any(frame.is_on_screen for frame in frames),
            ),
            MenuItem(
                "Expand All",
                self._expand_all,
                enabled=any(not frame.is_on_screen for frame in frames),
            ),
            MenuItem("Fit All", self._on_fit_all, enabled=bool(frames)),
        ]

    def _closed_entries(self, frames: list[Frame]) -> list[MenuSeparator | MenuItem]:
        """Return one entry per closed frame under a rule, or nothing if none are."""
        closed = [frame for frame in frames if frame.is_closed]
        if not closed:
            return []
        return [MenuSeparator(), *(self._reopen_item(frame) for frame in closed)]

    def _reopen_item(self, frame: Frame) -> MenuItem:
        """Build the entry that brings one closed frame back, by its title."""
        frame_id = frame.frame_id
        return MenuItem(frame.title, lambda: self._on_raise_frame(frame_id))

    def _collapse_all(self) -> None:
        """Send every frame that is on screen to the dock."""
        for frame in self._get_frames().values():
            if frame.is_on_screen:
                frame.minimize()

    def _expand_all(self) -> None:
        """Bring every frame back on screen — docked and closed alike.

        "Everything back on screen" is the whole meaning of the command, so a
        closed frame is included. It restores without taking focus: there is at
        most one focus request, so raising each in turn would keep only the last.
        """
        for frame in self._get_frames().values():
            frame.restore()
