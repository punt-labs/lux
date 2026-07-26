# pyright: reportMissingModuleSource=false
"""GeometryCapture — the render loop's ImGui-aware geometry adapter.

Wraps the ImGui-free :class:`GeometryRecorder` with the things only the render
tier supplies: which scene is currently painting, and the ImGui reads that turn
an open window or a just-painted leaf into a :class:`Rect` with its stack index.
Window-like adapters and the frame render seam call ``record_window`` /
``record_frame`` as they paint; the render seam calls ``record_item`` right after
a leaf paints. A geometry query reads the recorder's snapshot. Keeping the ImGui
reads here leaves the recorder pure and testable.
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
        """Record the current open window's rect and stack index for ``element_id``."""
        self._recorder.record_element(
            self._current_scene_id, element_id, self._window_rect(), self._stack_index()
        )

    def record_frame(self, frame_id: str) -> None:
        """Record the current open frame window's rect and stack index."""
        self._recorder.record_frame(frame_id, self._window_rect(), self._stack_index())

    def record_item(self, element_id: str) -> None:
        """Record the just-painted leaf's item rect and its window's stack index.

        Called right after a leaf's own widget paints, so ``get_item_rect``
        bounds that widget; the stack index is the window the leaf sits in, so a
        leaf inherits its window's front-to-back position.
        """
        self._recorder.record_element(
            self._current_scene_id, element_id, self._item_rect(), self._stack_index()
        )

    def complete(self) -> None:
        """Promote this frame's geometry into the snapshot a query reads."""
        self._recorder.complete()

    @staticmethod
    def _window_rect() -> Rect:
        """Read the current ImGui window's screen rect as a ``Rect``."""
        pos = imgui.get_window_pos()
        size = imgui.get_window_size()
        return Rect(x=pos.x, y=pos.y, width=size.x, height=size.y)

    @staticmethod
    def _item_rect() -> Rect:
        """Read the last-painted item's screen rect as a ``Rect``."""
        lo = imgui.get_item_rect_min()
        hi = imgui.get_item_rect_max()
        return Rect(x=lo.x, y=lo.y, width=hi.x - lo.x, height=hi.y - lo.y)

    @staticmethod
    def _stack_index() -> int:
        """Return the current window's position in ImGui's window order.

        ``begin_order_within_context`` is the order this window's ``Begin`` was
        called this frame; a modal begins after the frame beneath it, so its
        higher value reads as "in front".
        """
        return imgui.internal.get_current_window_read().begin_order_within_context
