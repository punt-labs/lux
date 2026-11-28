"""The Windows menu: where every frame is, and the commands that move it.

Split out of :class:`~punt_lux.display.menus.own_menus.OwnMenus` because the
frames are a concern of their own. That class knows about themes, opacity and
font size — none of which has anything to say about where a window sits — and
this one knows about nothing else.

Every entry reads live state at the moment the menu is composed, so a command
goes dim according to how the workspace is right now: Collapse All wants
something on screen to send away, Expand All wants something away to bring back.

The docked-frame entries at the bottom are a way back, beside the dock pill, for
a frame whose client owns no menu of its own: an ordinary ``show()`` scene's
frame, minimized to the dock, is restored here unchanged (DES-103 decision 6).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.display.menus.entries import MenuItem, MenuSeparator
from punt_lux.display.menus.hidden_id import MenuHiddenId
from punt_lux.display.menus.model import Submenu

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from punt_lux.display.replica.address_rendering import AddressRendering
    from punt_lux.display.replica.frame import Frame
    from punt_lux.display.window_chrome import WindowChromeCommands
    from punt_lux.wire.model.identity import HubId

__all__ = ["WindowsMenu"]


@final
class WindowsMenu:
    """Compose the Windows menu from the frames the display is holding."""

    _get_frames: Callable[[], Mapping[str, Frame]]
    _get_docked: Callable[[], Sequence[Frame]]
    _addressing: AddressRendering
    _on_clear_all: Callable[[], None]
    _on_fit_all: Callable[[], None]
    _on_raise_frame: Callable[[str, HubId], None]
    _chrome: WindowChromeCommands
    __slots__ = (
        "_addressing",
        "_chrome",
        "_get_docked",
        "_get_frames",
        "_on_clear_all",
        "_on_fit_all",
        "_on_raise_frame",
    )

    def __new__(
        cls,
        *,
        get_frames: Callable[[], Mapping[str, Frame]],
        get_docked: Callable[[], Sequence[Frame]],
        addressing: AddressRendering,
        on_clear_all: Callable[[], None],
        on_fit_all: Callable[[], None],
        on_raise_frame: Callable[[str, HubId], None],
        chrome: WindowChromeCommands,
    ) -> Self:
        self = super().__new__(cls)
        self._get_frames = get_frames
        self._get_docked = get_docked
        self._addressing = addressing
        self._on_clear_all = on_clear_all
        self._on_fit_all = on_fit_all
        self._on_raise_frame = on_raise_frame
        self._chrome = chrome
        return self

    def section(self) -> Submenu:
        """Build the menu: frame layout, the docked frames, then window chrome."""
        frames = list(self._get_frames().values())
        return Submenu(
            "Windows",
            [
                *self._layout_items(frames),
                *self._docked_entries(),
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

    def _docked_entries(self) -> list[MenuSeparator | MenuItem]:
        """Return one entry per docked frame under a rule, or nothing if none are.

        Read from the docked list, not the flattened frame map: two Hubs can hold
        a frame under one id, and each of those frames has its own pill.
        """
        docked = list(self._get_docked())
        if not docked:
            return []
        return [MenuSeparator(), *(self._reopen_item(frame) for frame in docked)]

    def _reopen_item(self, frame: Frame) -> MenuItem:
        """Build the reopen entry, ImGui-keyed on ``(frame.hub, frame_id)``."""
        frame_id = frame.frame_id
        label = MenuHiddenId.compose(
            self._addressing.frame_title(frame), f"{frame.hub.wire_token}:{frame_id}"
        )
        return MenuItem(label, lambda: self._on_raise_frame(frame_id, frame.hub))

    def _collapse_all(self) -> None:
        """Send every frame that is on screen to the dock."""
        for frame in self._get_frames().values():
            if frame.is_on_screen:
                frame.minimize()

    def _expand_all(self) -> None:
        """Bring every docked frame back on screen, taking no focus."""
        for frame in self._get_frames().values():
            frame.restore()
