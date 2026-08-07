"""DisplayFactProxy — the running display's own facts, as discriminated states.

``inspect_scene`` answers a scene's element tree from the Hub's authoritative
store, but one fact lives only on the display: where each element painted.
It is fetched over luxd's one bounded connection and narrowed here into a
discriminated state — ``unavailable`` with a reason when the round-trip
faults or the reply is malformed, the answer otherwise, and ``not_requested``
when the scope did not ask. This fact is read, never installed as Hub state
(introspection-api.md).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Self, cast, final

from punt_lux.operations.models.common import OpError
from punt_lux.operations.models.query_geometry import (
    GeometryNotRequested,
    GeometryPresent,
    GeometryUnavailable,
    SceneGeometry,
)

if TYPE_CHECKING:
    from punt_lux.operations.display_port import DisplayPort
    from punt_lux.operations.models.inspect_scope import InspectScope

__all__ = ["DisplayFactProxy"]


@final
class DisplayFactProxy:
    """Answer the display's own facts as discriminated states."""

    _port: DisplayPort
    __slots__ = ("_port",)

    def __new__(cls, port: DisplayPort) -> Self:
        self = super().__new__(cls)
        self._port = port
        return self

    def facts(self, scene_id: str, scope: InspectScope) -> SceneGeometry:
        """Return the scope's display facts."""
        if not scope.want_geometry:
            return GeometryNotRequested()
        return self.geometry(scene_id)

    def geometry(self, scene_id: str) -> SceneGeometry:
        """Proxy the display's painted geometry as a discriminated state."""
        payload = self._inspect({"scene_id": scene_id, "want_geometry": True})
        return self._geometry_from(payload)

    def _geometry_from(self, payload: Mapping[str, object] | OpError) -> SceneGeometry:
        """Derive the geometry state from an inspect reply's ``geometry`` block.

        A down display, a timeout, or a reply without a usable block is
        ``unavailable`` with a reason — distinct from "not requested". The rects
        are display-local truth, read here, never installed as Hub state.
        """
        if isinstance(payload, OpError):
            return GeometryUnavailable(reason=payload.reason)
        block = payload.get("geometry")
        if not isinstance(block, Mapping):
            return GeometryUnavailable(reason="display reply omitted geometry")
        try:
            return GeometryPresent.from_block(cast("Mapping[str, object]", block))
        except ValueError as exc:
            return GeometryUnavailable(reason=str(exc))

    def _inspect(self, params: dict[str, object]) -> Mapping[str, object] | OpError:
        """Proxy the display's ``inspect_scene``, resolving to a payload or error."""
        return self._port.query("inspect_scene", params).resolve()
