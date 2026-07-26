"""DisplayFactProxy — the running display's own facts, as discriminated states.

``inspect_scene`` answers a scene's element tree from the Hub's authoritative
store, but two facts live only on the display: whether every element is mirrored,
and where each element painted. Both are fetched over luxd's one bounded
connection and narrowed here into a discriminated state — ``not_requested`` is
never produced (the caller decides that), so each method returns ``unavailable``
with a reason when the round-trip faults or the reply is malformed, and the
answer otherwise. These facts are read, never installed as Hub state
(introspection-api.md).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Self, cast, final

from punt_lux.domain.ids import SceneId
from punt_lux.operations.models.common import OpError
from punt_lux.operations.models.query_geometry import (
    GeometryPresent,
    GeometryUnavailable,
    SceneGeometry,
)
from punt_lux.operations.models.query_mirror import (
    MirrorPresent,
    MirrorState,
    MirrorUnavailable,
)

if TYPE_CHECKING:
    from punt_lux.domain.hub.hub_display import HubDisplay
    from punt_lux.operations.display_port import DisplayPort

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

    def mirror(self, scene_id: str) -> MirrorState:
        """Proxy the display-side mirror check as a discriminated state.

        The display answers per element under ``element_paths``. The scene is
        present only when those paths account for *exactly* the Hub's elements:
        every Hub element mirrored (``mirrored == hub_count``) AND no extra
        entries beyond them (``len(entries) == hub_count``). The extras guard is
        what stops two mirrored elements plus one unmirrored extra from passing a
        bare count. The comparison is by count, not identity: ``element_paths``
        ids are not a usable identity key here — anonymous elements all carry
        ``""`` — so a set/multiset over them would not distinguish elements.

        An empty Hub scene is vacuously present; a Hub holding elements whose
        paths come back empty, short, or padded with extras is truthfully NOT
        present. A down display, a timeout, or a reply without the paths key is
        ``unavailable`` with a reason — distinct from "not requested".
        """
        payload = self._inspect({"scene_id": scene_id})
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

    def geometry(self, scene_id: str) -> SceneGeometry:
        """Proxy the display's painted geometry as a discriminated state.

        The display answers ``inspect_scene`` with a ``geometry`` block when
        asked. A down display, a timeout, or a reply without a usable block is
        ``unavailable`` with a reason — distinct from "not requested". The rects
        are display-local truth, read here, never installed as Hub state.
        """
        payload = self._inspect({"scene_id": scene_id, "want_geometry": True})
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
