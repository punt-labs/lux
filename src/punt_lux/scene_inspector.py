"""SceneInspector — the enriched ``inspect_scene`` query handler."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Self

from punt_lux.scene_inspection import SceneInspection

if TYPE_CHECKING:
    from punt_lux.display.geometry import GeometryRecorder
    from punt_lux.display.replica import SceneReplica

__all__ = ["SceneInspector"]


class SceneInspector:
    """Answer ``inspect_scene`` with resolved_props per element.

    Composes the display's ``SceneReplica`` (the rendered element objects) and
    the render loop's ``GeometryRecorder`` (painted rects). Registered on the
    ``QueryDispatcher`` by ``DisplayServer``, overriding the built-in that
    reads ``SceneReplica`` alone — the extra store is why this lives here and
    not on the dispatcher.
    """

    _scenes: SceneReplica
    _geometry: GeometryRecorder

    def __new__(
        cls,
        *,
        scenes: SceneReplica,
        geometry: GeometryRecorder,
    ) -> Self:
        self = super().__new__(cls)
        self._scenes = scenes
        self._geometry = geometry
        return self

    def inspect(
        self,
        scene_id: str = "",
        *,
        want_geometry: bool = False,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        """Return the enriched inspection, or raise ``LookupError`` if absent.

        When ``want_geometry`` is set, the reply carries a ``geometry`` block
        with each painted element's screen rect and the scene's frame rect, read
        from the last completed frame. An element not painted last frame is
        absent from the block — reported directly, not as a zero rect.
        """
        scene = self._scenes.resolve_scene(scene_id)
        if scene is None:
            msg = f"Scene '{scene_id}' not found"
            raise LookupError(msg)
        inspection = SceneInspection.from_scene(scene_id, scene.elements)
        result = inspection.to_dict()
        if want_geometry:
            # A resolved scene is found through ``scene_to_frame``, so it is
            # always mapped here; indexing (not ``.get``) turns any divergence
            # into a KeyError the dispatcher reports as geometry-unavailable,
            # rather than a missing entry masquerading as a not-painted frame.
            frame_id = self._scenes.scene_to_frame[scene_id]
            result["geometry"] = self._geometry.snapshot().to_wire(scene_id, frame_id)
        return result
