"""Frame — a named inner window holding one or more scenes."""

from __future__ import annotations

from typing import Literal, Self

from punt_lux.display.replica.frame_visibility import FrameVisibility
from punt_lux.protocol import SceneMessage


class Frame:
    """A named inner window in the workspace.

    Each frame owns one or more scenes contributed by one or more clients.
    When ``layout`` is ``"tab"`` (default), multiple scenes appear as tabs;
    when ``"stack"``, they stack vertically with collapsing headers.

    Where the frame is — on screen, docked, or put away — is asked through the
    three predicates and moved through the three mutators. There is no flag to
    assign, because assignment is how a content event used to reach in and undo
    the user's decision (DES-065 R8).
    """

    _frame_id: str
    _title: str
    _owner_fds: set[int]
    _scenes: dict[str, SceneMessage]
    _scene_order: list[str]
    _active_tab: str | None
    _visibility: FrameVisibility
    _cascade_index: int
    _initial_size: tuple[int, int] | None
    _flags: dict[str, bool] | None
    _layout: Literal["tab", "stack"]

    def __new__(
        cls,
        *,
        frame_id: str,
        title: str,
        owner_fds: set[int],
        scenes: dict[str, SceneMessage],
        scene_order: list[str],
        active_tab: str | None = None,
        visibility: FrameVisibility = FrameVisibility.ON_SCREEN,
        cascade_index: int = 0,
        initial_size: tuple[int, int] | None = None,
        flags: dict[str, bool] | None = None,
        layout: Literal["tab", "stack"] = "tab",
    ) -> Self:
        self = super().__new__(cls)
        self._frame_id = frame_id
        self._title = title
        self._owner_fds = owner_fds
        self._scenes = scenes
        self._scene_order = scene_order
        self._active_tab = active_tab
        self._visibility = visibility
        self._cascade_index = cascade_index
        self._initial_size = initial_size
        self._flags = flags
        self._layout = layout
        return self

    # -- read-only properties ------------------------------------------------

    @property
    def frame_id(self) -> str:
        """Return the unique identifier for this frame."""
        return self._frame_id

    @property
    def cascade_index(self) -> int:
        """Return the cascade position index."""
        return self._cascade_index

    @property
    def initial_size(self) -> tuple[int, int] | None:
        """Return the initial window size, if set."""
        return self._initial_size

    @property
    def owner_fds(self) -> set[int]:
        """Return the set of owning file descriptors."""
        return self._owner_fds

    @property
    def scenes(self) -> dict[str, SceneMessage]:
        """Return the scene map."""
        return self._scenes

    # -- mutable properties --------------------------------------------------

    @property
    def scene_order(self) -> list[str]:
        """Return the ordered list of scene IDs."""
        return self._scene_order

    @scene_order.setter
    def scene_order(self, value: list[str]) -> None:
        self._scene_order = value

    @property
    def title(self) -> str:
        """Return the frame title."""
        return self._title

    @title.setter
    def title(self, value: str) -> None:
        self._title = value

    @property
    def active_tab(self) -> str | None:
        """Return the active tab scene ID."""
        return self._active_tab

    @active_tab.setter
    def active_tab(self, value: str | None) -> None:
        self._active_tab = value

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

    # -- visibility ----------------------------------------------------------

    @property
    def visibility(self) -> FrameVisibility:
        """Return where the frame is: on screen, docked, or put away."""
        return self._visibility

    @property
    def is_on_screen(self) -> bool:
        """Return whether the frame is painted as an inner window."""
        return self._visibility.is_on_screen

    @property
    def is_docked(self) -> bool:
        """Return whether the frame is in the dock bar, carrying a pill."""
        return self._visibility.is_docked

    @property
    def is_closed(self) -> bool:
        """Return whether the user has put the frame away."""
        return self._visibility.is_closed

    def minimize(self) -> None:
        """Put the frame in the dock: not painted, but still carrying a pill."""
        self._visibility = FrameVisibility.DOCKED

    def close(self) -> None:
        """Put the frame away: not painted, and carrying no pill.

        Visibility only. The frame keeps its scenes, its widget state, its active
        tab and its cascade index, so a later restore brings back what the user
        shut rather than something rebuilt from a fresh push.
        """
        self._visibility = FrameVisibility.CLOSED

    def restore(self) -> None:
        """Bring the frame back on screen, from docked and closed alike."""
        self._visibility = FrameVisibility.ON_SCREEN
