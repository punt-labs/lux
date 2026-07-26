"""SceneInspector — the enriched ``inspect_scene`` query handler."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Self

from punt_lux.domain.ids import SceneId
from punt_lux.scene_inspection import SceneInspection

if TYPE_CHECKING:
    from punt_lux.display.geometry import GeometryRecorder
    from punt_lux.domain.display import Display
    from punt_lux.scene import SceneManager

__all__ = ["SceneInspector"]


class SceneInspector:
    """Answer ``inspect_scene`` with render_path + resolved_props per element.

    Composes the display's ``SceneManager`` (the rendered element objects), its
    domain ``Display`` mirror (element mirror-presence), and the render loop's
    ``GeometryRecorder`` (painted rects). Registered on the ``QueryDispatcher``
    by ``DisplayServer``, overriding the built-in that reads ``SceneManager``
    alone — the extra stores are why this lives here and not on the dispatcher.
    """

    _scenes: SceneManager
    _mirror: Display
    _geometry: GeometryRecorder

    def __new__(
        cls,
        *,
        scene_manager: SceneManager,
        domain_display: Display,
        geometry: GeometryRecorder,
    ) -> Self:
        self = super().__new__(cls)
        self._scenes = scene_manager
        self._mirror = domain_display
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
        inspection = SceneInspection.from_scene(
            scene_id, scene.elements, mirror_ids=self._mirror_ids(scene_id)
        )
        result = inspection.to_dict()
        if want_geometry:
            # A resolved scene is found through ``scene_to_frame``, so it is
            # always mapped here; indexing (not ``.get``) turns any divergence
            # into a KeyError the dispatcher reports as geometry-unavailable,
            # rather than a missing entry masquerading as a not-painted frame.
            frame_id = self._scenes.scene_to_frame[scene_id]
            result["geometry"] = self._geometry.snapshot().to_wire(scene_id, frame_id)
        return result

    def _mirror_ids(self, scene_id: str) -> frozenset[str]:
        """Return the element ids the pump routed into the display's mirror.

        Empty when the scene never reached the mirror — the pump skips a scene
        containing any non-native kind, so ``domain_mirror_present`` is only
        deterministic for an all-native scene.
        """
        try:
            snapshot = self._mirror.snapshot(SceneId(scene_id))
        except KeyError:
            return frozenset()
        return frozenset(str(eid) for eid in snapshot.element_ids)
