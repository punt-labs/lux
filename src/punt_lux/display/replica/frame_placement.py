"""FramePlacement -- a frame's visibility, active tab, and cascade slot.

Grouped into one composed value because :meth:`Frame.presentation` already
reports them as one unit, and all three change together under the same three
gestures (minimize/close/restore) a frame's placement -- never its content --
answers to.
"""

from __future__ import annotations

from typing import Self, final

from punt_lux.display.replica.frame_visibility import FrameVisibility

__all__ = ["FramePlacement"]


@final
class FramePlacement:
    """Where a frame is on screen: visibility, active tab, cascade slot."""

    _visibility: FrameVisibility
    _active_tab: str | None
    _cascade_index: int
    __slots__ = ("_active_tab", "_cascade_index", "_visibility")

    def __new__(
        cls,
        *,
        visibility: FrameVisibility = FrameVisibility.ON_SCREEN,
        active_tab: str | None = None,
        cascade_index: int = 0,
    ) -> Self:
        self = super().__new__(cls)
        self._visibility = visibility
        self._active_tab = active_tab
        self._cascade_index = cascade_index
        return self

    @property
    def visibility(self) -> FrameVisibility:
        return self._visibility

    @property
    def is_on_screen(self) -> bool:
        return self._visibility.is_on_screen

    @property
    def is_docked(self) -> bool:
        return self._visibility.is_docked

    @property
    def is_closed(self) -> bool:
        return self._visibility.is_closed

    @property
    def active_tab(self) -> str | None:
        return self._active_tab

    @active_tab.setter
    def active_tab(self, value: str | None) -> None:
        self._active_tab = value

    @property
    def cascade_index(self) -> int:
        return self._cascade_index

    def minimize(self) -> None:
        self._visibility = FrameVisibility.DOCKED

    def close(self) -> None:
        self._visibility = FrameVisibility.CLOSED

    def restore(self) -> None:
        self._visibility = FrameVisibility.ON_SCREEN
