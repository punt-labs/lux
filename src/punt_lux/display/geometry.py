"""Per-frame painted geometry the Display captures and a geometry query reads.

The render loop writes each painted element's screen rect and Z-order and each
frame window's rect and stacking into a :class:`GeometryRecorder` as it paints;
at frame end it calls ``complete()`` to promote that frame's captures into the
immutable :class:`GeometrySnapshot` a geometry query answers from.

Write and read happen on the one render thread: the query is dispatched inside
``poll_clients`` at the top of the next frame, before that frame's
``_render_scene`` clears the recorder, so the snapshot is always a whole
completed frame and no lock guards it.

An element present in a scene's tree but absent from the snapshot was not
painted last frame — a collapsed header's child, a closed modal's child, a
clipped row. Its absence reports that directly, never a zero rect.
"""

from __future__ import annotations

from typing import Self

from punt_lux.protocol.geometry import Rect
from punt_lux.protocol.painted_geometry import ElementGeometry, FrameGeometry

__all__ = ["GeometryRecorder", "GeometrySnapshot"]


class GeometrySnapshot:
    """The painted geometry of one completed frame, keyed for per-scene readback.

    Elements are keyed by ``(scene_id, element_id)`` because element ids are
    unique only within their scene — two scenes may each hold a ``"submit"``
    button, and their geometry must not overwrite one another.
    """

    _elements: dict[tuple[str, str], ElementGeometry]
    _frames: dict[str, FrameGeometry]
    __slots__ = ("_elements", "_frames")

    def __new__(
        cls,
        elements: dict[tuple[str, str], ElementGeometry],
        frames: dict[str, FrameGeometry],
    ) -> Self:
        self = super().__new__(cls)
        self._elements = dict(elements)
        self._frames = dict(frames)
        return self

    @classmethod
    def empty(cls) -> Self:
        """Return the snapshot that stands before any frame has completed."""
        return cls({}, {})

    def element_for(self, scene_id: str, element_id: str) -> ElementGeometry | None:
        """Return the element's painted geometry, or ``None`` if not painted.

        Absence is the documented contract (PY-EH-8): an element in the scene
        tree but not painted last frame has no geometry, and the ``None`` says so.
        """
        return self._elements.get((scene_id, element_id))

    def frame_for(self, frame_id: str) -> FrameGeometry | None:
        """Return the frame window's painted geometry, or ``None`` if not painted."""
        return self._frames.get(frame_id)

    def to_wire(self, scene_id: str, frame_id: str) -> dict[str, object]:
        """Return the geometry reply for one scene: element geometry plus the frame.

        ``elements`` maps each painted element id in ``scene_id`` to its geometry
        dict (rect plus paint sequence and stack index); ``frame`` is the scene's
        frame geometry, or ``None`` when that frame was not painted last frame.
        """
        elements = {
            element_id: geometry.to_dict()
            for (sid, element_id), geometry in self._elements.items()
            if sid == scene_id
        }
        frame = self._frames.get(frame_id)
        return {
            "elements": elements,
            "frame": frame.to_dict() if frame is not None else None,
        }


class GeometryRecorder:
    """Accumulate the current frame's painted geometry; promote it on completion.

    The render loop records into the *building* maps as it paints, then calls
    ``complete()`` once at frame end to swap them into the immutable snapshot and
    start the next frame's accumulation fresh. Each element is stamped with the
    next paint-sequence number, so the record order the render loop already paints
    in becomes an explicit field rather than an implicit dict ordering.
    """

    _building_elements: dict[tuple[str, str], ElementGeometry]
    _building_frames: dict[str, FrameGeometry]
    _next_sequence: int
    _completed: GeometrySnapshot
    __slots__ = (
        "_building_elements",
        "_building_frames",
        "_completed",
        "_next_sequence",
    )

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._building_elements = {}
        self._building_frames = {}
        self._next_sequence = 0
        self._completed = GeometrySnapshot.empty()
        return self

    def record_element(
        self, scene_id: str, element_id: str, rect: Rect, stack_index: int
    ) -> None:
        """Record one painted element's rect, paint order, and window stack index."""
        self._building_elements[scene_id, element_id] = ElementGeometry(
            rect=rect, paint_sequence=self._next_sequence, stack_index=stack_index
        )
        self._next_sequence += 1

    def record_frame(self, frame_id: str, rect: Rect, stack_index: int) -> None:
        """Record one frame window's rect and its position in ImGui's window order."""
        self._building_frames[frame_id] = FrameGeometry(
            rect=rect, stack_index=stack_index
        )

    def complete(self) -> None:
        """Promote the building geometry into the completed snapshot; reset building.

        A whole-frame swap, so a reader between frames sees the previous frame
        entire — never a half-painted mix of this frame and the last. The
        paint-sequence counter restarts, so each frame's sequence starts at zero.
        """
        self._completed = GeometrySnapshot(
            self._building_elements, self._building_frames
        )
        self._building_elements = {}
        self._building_frames = {}
        self._next_sequence = 0

    def snapshot(self) -> GeometrySnapshot:
        """Return the last completed frame's snapshot."""
        return self._completed
