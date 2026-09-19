"""Frame — a named inner window holding one or more scenes."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, Self, final

from punt_lux.display.replica.frame_placement import FramePlacement
from punt_lux.display.replica.frame_visibility import FrameVisibility
from punt_lux.display.replica.window_hints import WindowHints
from punt_lux.protocol import SceneMessage

if TYPE_CHECKING:
    from punt_lux.domain.identity import HubId


@final
class Frame:
    """A named inner window in the workspace, owned by one Hub. Where the
    frame is -- on screen, docked, or put away -- is asked through the
    three predicates and moved through the three mutators; there is no
    flag to assign (DES-065 R8). Visibility, active tab, and cascade slot
    are a composed :class:`FramePlacement`, not three separate fields."""

    _hub: HubId
    _frame_id: str
    _title: str
    _owner_fds: set[int]
    _scenes: dict[str, SceneMessage]
    _scene_order: list[str]
    _placement: FramePlacement
    _hints: WindowHints
    __slots__ = (
        "_frame_id",
        "_hints",
        "_hub",
        "_owner_fds",
        "_placement",
        "_scene_order",
        "_scenes",
        "_title",
    )

    def __new__(
        cls,
        *,
        hub: HubId,
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
        self._hub = hub
        self._frame_id = frame_id
        self._title = title
        self._owner_fds = owner_fds
        self._scenes = scenes
        self._scene_order = scene_order
        self._placement = FramePlacement(
            visibility=visibility, active_tab=active_tab, cascade_index=cascade_index
        )
        self._hints = WindowHints(initial_size=initial_size, flags=flags, layout=layout)
        return self

    @property
    def hub(self) -> HubId:
        return self._hub

    @property
    def frame_id(self) -> str:
        return self._frame_id

    @property
    def cascade_index(self) -> int:
        return self._placement.cascade_index

    @property
    def initial_size(self) -> tuple[int, int] | None:
        return self._hints.initial_size

    @property
    def hints(self) -> WindowHints:
        """The window's ImGui creation hints: flags and layout."""
        return self._hints

    @property
    def owner_fds(self) -> set[int]:
        return self._owner_fds

    @property
    def scenes(self) -> dict[str, SceneMessage]:
        return self._scenes

    @property
    def scene_order(self) -> list[str]:
        return self._scene_order

    @scene_order.setter
    def scene_order(self, value: list[str]) -> None:
        self._scene_order = value

    @property
    def title(self) -> str:
        return self._title

    @title.setter
    def title(self, value: str) -> None:
        self._title = value

    @property
    def active_tab(self) -> str | None:
        return self._placement.active_tab

    @active_tab.setter
    def active_tab(self, value: str | None) -> None:
        self._placement.active_tab = value

    @property
    def visibility(self) -> FrameVisibility:
        return self._placement.visibility

    @property
    def is_on_screen(self) -> bool:
        return self._placement.is_on_screen

    @property
    def is_docked(self) -> bool:
        """Whether the frame is in the dock bar, carrying a pill."""
        return self._placement.is_docked

    @property
    def is_closed(self) -> bool:
        return self._placement.is_closed

    def minimize(self) -> None:
        """Put the frame in the dock: not painted, but still carrying a pill."""
        self._placement.minimize()

    def close(self) -> None:
        """Put the frame away: not painted, no pill -- visibility only, so a
        later restore brings back what the user shut, not a fresh rebuild."""
        self._placement.close()

    def restore(self) -> None:
        """Bring the frame back on screen, from docked and closed alike."""
        self._placement.restore()

    def presentation(self) -> dict[str, object]:
        """Return this frame's Display-owned facts, keyed like ``FramePresentation``."""
        return {
            "frame_id": self._frame_id,
            "visibility": self._placement.visibility.value,
            "active_tab": self._placement.active_tab,
            "cascade_index": self._placement.cascade_index,
        }
