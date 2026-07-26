# pyright: reportMissingModuleSource=false
"""GeometryCapture — the render loop's ImGui-aware geometry adapter.

Wraps the ImGui-free :class:`GeometryRecorder` with the two things only the
render tier supplies: which scene is currently painting, and the ImGui reads
that turn an open window into a :class:`Rect`. The window-like adapters and the
frame render seam call this as they paint; a geometry query reads the recorder's
snapshot. Keeping the ImGui reads here leaves the recorder pure and testable.
"""

from __future__ import annotations

from typing import Self

from imgui_bundle import imgui

from punt_lux.display.geometry import GeometryRecorder
from punt_lux.protocol.geometry import Rect

__all__ = ["GeometryCapture"]


class GeometryCapture:
    """Record painted rects from ImGui into the recorder, scoped to a scene."""

    _recorder: GeometryRecorder
    _current_scene_id: str
    __slots__ = ("_current_scene_id", "_recorder")

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._recorder = GeometryRecorder()
        self._current_scene_id = ""
        return self

    @property
    def recorder(self) -> GeometryRecorder:
        """Return the recorder a geometry query reads its snapshot from."""
        return self._recorder

    def enter_scene(self, scene_id: str) -> None:
        """Set the scene being painted so recorded rects key to it."""
        self._current_scene_id = scene_id

    def record_window(self, element_id: str) -> None:
        """Record the current open window's screen rect for ``element_id``."""
        self._recorder.record_element(
            self._current_scene_id, element_id, self._window_rect()
        )

    def record_frame(self, frame_id: str) -> None:
        """Record the current open frame window's screen rect."""
        self._recorder.record_frame(frame_id, self._window_rect())

    def complete(self) -> None:
        """Promote this frame's rects into the snapshot a query reads."""
        self._recorder.complete()

    @staticmethod
    def _window_rect() -> Rect:
        """Read the current ImGui window's screen rect as a ``Rect``."""
        pos = imgui.get_window_pos()
        size = imgui.get_window_size()
        return Rect(x=pos.x, y=pos.y, width=size.x, height=size.y)
