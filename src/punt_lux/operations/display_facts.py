"""DisplayFactProxy — the running display's own facts, as discriminated states.

``inspect_scene`` answers a scene's element tree from the Hub's authoritative
store, but two facts live only on the display: whether every element is mirrored,
and where each element painted. Both are fetched over luxd's one bounded
connection and narrowed here into a discriminated state — ``unavailable`` with a
reason when the round-trip faults or the reply is malformed, the answer
otherwise, and ``not_requested`` for a fact the scope did not ask for. These
facts are read, never installed as Hub state (introspection-api.md).

When a scope wants both facts, ``facts`` issues one round-trip carrying both
flags and derives both from that single reply, so the two are frame-coherent: a
mirror check and a geometry read can never disagree by landing on different
completed frames. A scope wanting one fact issues its one single-flag query.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Self, cast, final

from punt_lux.domain.ids import SceneId
from punt_lux.operations.models.common import OpError
from punt_lux.operations.models.query_geometry import (
    GeometryNotRequested,
    GeometryPresent,
    GeometryUnavailable,
    SceneGeometry,
)
from punt_lux.operations.models.query_mirror import (
    MirrorNotRequested,
    MirrorPresent,
    MirrorState,
    MirrorUnavailable,
)

if TYPE_CHECKING:
    from punt_lux.domain.hub.hub_display import HubDisplay
    from punt_lux.operations.display_port import DisplayPort
    from punt_lux.operations.models.inspect_scope import InspectScope

__all__ = ["DisplayFactProxy"]


@final
class DisplayFactProxy:
    """Answer the display's mirror and geometry facts as discriminated states."""

    _display: HubDisplay
    _port: DisplayPort
    __slots__ = ("_display", "_port")

    def __new__(cls, display: HubDisplay, port: DisplayPort) -> Self:
        self = super().__new__(cls)
        self._display = display
        self._port = port
        return self

    def facts(
        self, scene_id: str, scope: InspectScope
    ) -> tuple[MirrorState, SceneGeometry]:
        """Return the scope's display facts from as few round-trips as serve them.

        When the scope wants both the mirror check and geometry, ONE
        ``inspect_scene`` carries both flags and both facts derive from that
        single reply — the frame-coherence guarantee (the two cannot disagree by
        landing on different completed frames). A scope wanting one fact issues
        its one single-flag query; a scope wanting neither issues no round-trip.
        """
        if scope.want_mirror and scope.want_geometry:
            payload = self._inspect({"scene_id": scene_id, "want_geometry": True})
            return self._mirror_from(payload, scene_id), self._geometry_from(payload)
        mirror = self.mirror(scene_id) if scope.want_mirror else MirrorNotRequested()
        geometry = (
            self.geometry(scene_id) if scope.want_geometry else GeometryNotRequested()
        )
        return mirror, geometry

    def mirror(self, scene_id: str) -> MirrorState:
        """Proxy the display-side mirror check as a discriminated state."""
        return self._mirror_from(self._inspect({"scene_id": scene_id}), scene_id)

    def geometry(self, scene_id: str) -> SceneGeometry:
        """Proxy the display's painted geometry as a discriminated state."""
        payload = self._inspect({"scene_id": scene_id, "want_geometry": True})
        return self._geometry_from(payload)

    def _mirror_from(
        self, payload: Mapping[str, object] | OpError, scene_id: str
    ) -> MirrorState:
        """Derive the mirror state from an inspect reply's ``element_paths``.

        The scene is present only when the paths account for *exactly* the Hub's
        elements: every Hub element mirrored (``mirrored == hub_count``) AND no
        extra entries beyond them (``len(entries) == hub_count``). The extras
        guard is what stops two mirrored elements plus one unmirrored extra from
        passing a bare count. The comparison is by count, not identity:
        ``element_paths`` ids are not a usable identity key here — anonymous
        elements all carry ``""`` — so a set/multiset over them would not
        distinguish elements.

        An empty Hub scene is vacuously present; a Hub holding elements whose
        paths come back empty, short, or padded with extras is truthfully NOT
        present. A down display, a timeout, or a reply without the paths key is
        ``unavailable`` with a reason — distinct from "not requested".
        """
        if isinstance(payload, OpError):
            return MirrorUnavailable(reason=payload.reason)
        paths = payload.get("element_paths")
        if not isinstance(paths, list):
            return MirrorUnavailable(reason="display reply omitted element_paths")
        entries = cast("list[object]", paths)
        mirrored = sum(
            1
            for entry in entries
            if isinstance(entry, Mapping)
            and bool(cast("Mapping[str, object]", entry).get("domain_mirror_present"))
        )
        hub_count = self._display.element_count(SceneId(scene_id))
        present = mirrored == hub_count and len(entries) == hub_count
        return MirrorPresent(present=present)

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
