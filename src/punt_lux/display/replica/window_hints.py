"""WindowHints — a frame's ImGui window-creation size, flags, and tab layout."""

from __future__ import annotations

from typing import Literal, Self, final


@final
class WindowHints:
    """The initial size, named ImGui flags, and layout mode a frame's window carries."""

    _initial_size: tuple[int, int] | None
    _flags: dict[str, bool] | None
    _layout: Literal["tab", "stack"]
    __slots__ = ("_flags", "_initial_size", "_layout")

    def __new__(
        cls,
        *,
        initial_size: tuple[int, int] | None = None,
        flags: dict[str, bool] | None = None,
        layout: Literal["tab", "stack"] = "tab",
    ) -> Self:
        self = super().__new__(cls)
        self._initial_size = initial_size
        self._flags = flags
        self._layout = layout
        return self

    @property
    def initial_size(self) -> tuple[int, int] | None:
        """Return the initial window size, if set."""
        return self._initial_size

    @property
    def flags(self) -> dict[str, bool] | None:
        """Return the window flags dict."""
        return self._flags

    @flags.setter
    def flags(self, value: dict[str, bool] | None) -> None:
        self._flags = value

    @property
    def layout(self) -> Literal["tab", "stack"]:
        """Return the layout mode."""
        return self._layout

    @layout.setter
    def layout(self, value: Literal["tab", "stack"]) -> None:
        self._layout = value
