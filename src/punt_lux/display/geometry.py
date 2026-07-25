"""Per-frame painted geometry the Display captures and a geometry query reads.

The render loop writes each painted element's screen rect and each frame
window's rect into a :class:`GeometryRecorder` as it paints; at frame end it
calls ``complete()`` to promote that frame's rects into the immutable
:class:`GeometrySnapshot` a geometry query answers from.

Write and read happen on the one render thread: the query is dispatched inside
``poll_clients`` at the top of the next frame, before that frame's
``_render_scene`` clears the recorder, so the snapshot is always a whole
completed frame and no lock guards it.

An element present in a scene's tree but absent from the snapshot was not
painted last frame — a collapsed header's child, a closed modal's child, a
clipped row. Its absence is the honest answer, never a zero rect.
"""

from __future__ import annotations

from typing import Self

from punt_lux.protocol.geometry import Rect

__all__ = ["GeometryRecorder", "GeometrySnapshot"]


class GeometrySnapshot:
    """The painted rects of one completed frame, keyed for per-scene readback.

    Element rects are keyed by ``(scene_id, element_id)`` because element ids are
    unique only within their scene — two scenes may each hold a ``"submit"``
    button, and their rects must not overwrite one another.
    """

    _elements: dict[tuple[str, str], Rect]
    _frames: dict[str, Rect]
    __slots__ = ("_elements", "_frames")

    def __new__(
        cls,
        elements: dict[tuple[str, str], Rect],
        frames: dict[str, Rect],
    ) -> Self:
        self = super().__new__(cls)
        self._elements = dict(elements)
        self._frames = dict(frames)
        return self

    @classmethod
    def empty(cls) -> Self:
        """Return the snapshot that stands before any frame has completed."""
        return cls({}, {})

    def rect_for(self, scene_id: str, element_id: str) -> Rect | None:
        """Return the element's painted rect, or ``None`` if it was not painted.

        Absence is the documented contract (PY-EH-8): an element in the scene
        tree but not painted last frame has no rect, and the ``None`` says so.
        """
        return self._elements.get((scene_id, element_id))

    def frame_rect(self, frame_id: str) -> Rect | None:
        """Return the frame window's painted rect, or ``None`` if not painted."""
        return self._frames.get(frame_id)

    def to_wire(self, scene_id: str, frame_id: str | None) -> dict[str, object]:
        """Return the geometry reply for one scene: element rects plus frame rect.

        ``elements`` maps each painted element id in ``scene_id`` to its rect
        dict; ``frame`` is the scene's frame rect, or ``None`` when that frame
        was not painted last frame.
        """
        elements = {
            element_id: rect.to_dict()
            for (sid, element_id), rect in self._elements.items()
            if sid == scene_id
        }
        frame = self._frames.get(frame_id) if frame_id is not None else None
        return {
            "elements": elements,
            "frame": frame.to_dict() if frame is not None else None,
        }


class GeometryRecorder:
    """Accumulate the current frame's painted rects; promote them on completion.

    The render loop records into the *building* maps as it paints, then calls
    ``complete()`` once at frame end to swap them into the immutable snapshot and
    start the next frame's accumulation fresh.
    """

    _building_elements: dict[tuple[str, str], Rect]
    _building_frames: dict[str, Rect]
    _completed: GeometrySnapshot
    __slots__ = ("_building_elements", "_building_frames", "_completed")

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._building_elements = {}
        self._building_frames = {}
        self._completed = GeometrySnapshot.empty()
        return self

    def record_element(self, scene_id: str, element_id: str, rect: Rect) -> None:
        """Record one painted element's screen rect for the current frame."""
        self._building_elements[scene_id, element_id] = rect

    def record_frame(self, frame_id: str, rect: Rect) -> None:
        """Record one frame window's screen rect for the current frame."""
        self._building_frames[frame_id] = rect

    def complete(self) -> None:
        """Promote the building rects into the completed snapshot; reset building.

        A whole-frame swap, so a reader between frames sees the previous frame
        entire — never a half-painted mix of this frame and the last.
        """
        self._completed = GeometrySnapshot(
            self._building_elements, self._building_frames
        )
        self._building_elements = {}
        self._building_frames = {}

    def snapshot(self) -> GeometrySnapshot:
        """Return the last completed frame's snapshot."""
        return self._completed
