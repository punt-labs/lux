"""QueryOperations — the read surface, Hub-authoritative where it can be.

``inspect_scene``, ``list_scenes``, and ``list_clients`` read the authoritative
Hub state directly: the element store, its presentations, and the session
registry. This is the reach-around removal — asking the authority, not the
display replica. ``list_recent_events`` and ``list_errors`` are facts about the
running display's own ring buffers, so they proxy over luxd's one connection.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Literal, Self, cast, final

from punt_lux.domain.element_abc import Element as ElementABC
from punt_lux.domain.ids import SceneId
from punt_lux.domain.inspectable import Inspectable
from punt_lux.domain.validation_walk import HasChildElements
from punt_lux.operations.models.common import OpError
from punt_lux.operations.models.query_clients import ClientList, HubClient
from punt_lux.operations.models.query_errors import RecentErrors
from punt_lux.operations.models.query_events import RecentEvents
from punt_lux.operations.models.query_inspection import (
    InspectedElement,
    MirrorNotRequested,
    MirrorPresent,
    MirrorState,
    MirrorUnavailable,
    SceneInspection,
)
from punt_lux.operations.models.query_scenes import (
    FrameSummary,
    SceneList,
    SceneSummary,
)
from punt_lux.protocol.elements import element_to_dict

if TYPE_CHECKING:
    from punt_lux.domain.hub.hub import Hub
    from punt_lux.domain.hub.hub_display import HubDisplay
    from punt_lux.operations.display_port import DisplayPort
    from punt_lux.protocol import Element as WireElement

__all__ = ["QueryOperations"]


@final
class QueryOperations:
    """Answer read queries from the Hub, proxying only the display's own facts."""

    _display: HubDisplay
    _hub: Hub
    _port: DisplayPort
    __slots__ = ("_display", "_hub", "_port")

    def __new__(cls, display: HubDisplay, hub: Hub, port: DisplayPort) -> Self:
        self = super().__new__(cls)
        self._display = display
        self._hub = hub
        self._port = port
        return self

    # -- Hub-authoritative reads -------------------------------------------

    def inspect_scene(
        self, scene_id: str, *, want_mirror: bool = False
    ) -> SceneInspection | OpError:
        """Return a scene's element tree read from the authoritative store.

        Reads ``HubDisplay`` — never the display replica. An unknown scene is a
        ``not_found``. The display-side mirror check is proxied only when asked
        and is never treated as Hub authority.
        """
        sid = SceneId(scene_id)
        if sid not in self._display.live_scene_ids():
            return OpError(code="not_found", reason=f"scene {scene_id!r} not found")
        # The store hands back domain elements; they are structurally the wire
        # Element the codec and the ABC checks read (PY-TS-12 domain/wire bridge).
        elements = [
            self._inspect(cast("WireElement", root))
            for root in self._display.scene_roots(sid)
        ]
        mirror = self._mirror(scene_id) if want_mirror else MirrorNotRequested()
        return SceneInspection(scene_id=scene_id, elements=elements, mirror=mirror)

    def list_scenes(self) -> SceneList:
        """List every live scene and frame from the authoritative store."""
        scenes: list[SceneSummary] = []
        frames: dict[str, _FrameAccumulator] = {}
        for sid in self._display.live_scene_ids():
            presentation = self._display.presentation_for(sid)
            owner = self._display.scene_owner(sid)
            scenes.append(
                SceneSummary(
                    scene_id=str(sid),
                    element_count=self._display.element_count(sid),
                    frame_id=presentation.frame_id,
                    owner=str(owner) if owner is not None else None,
                )
            )
            layout = presentation.frame_layout or "tab"
            frame = frames.setdefault(
                presentation.frame_id,
                _FrameAccumulator(
                    title=presentation.frame_title or presentation.frame_id,
                    layout=layout,
                ),
            )
            frame.add(str(sid))
        return SceneList(
            scenes=scenes,
            frames=[acc.summary(fid) for fid, acc in frames.items()],
        )

    def list_clients(self, *, now: float) -> ClientList:
        """List the Hub's sessions — the meaningful client answer post-replicator."""
        clients = [
            HubClient(
                connection_id=str(connection_id),
                connected_seconds=round(now - connected_at, 1),
                subscribed_topics=sorted(
                    str(topic) for topic in self._hub.topics_for(connection_id)
                ),
                owned_scenes=sorted(
                    {
                        str(scene)
                        for scene, _elem in self._display.elements_owned_by(
                            connection_id
                        )
                    }
                ),
            )
            for connection_id, connected_at in self._display.client_sessions().items()
        ]
        return ClientList(clients=clients)

    # -- proxied display facts ---------------------------------------------

    def list_recent_events(self, count: int) -> RecentEvents | OpError:
        """Return the display's recent interactions, proxied over one connection."""
        payload = self._port.query("list_recent_events", {"count": count}).resolve()
        if isinstance(payload, OpError):
            return payload
        return RecentEvents.from_payload(payload)

    def list_errors(self, count: int) -> RecentErrors | OpError:
        """Return the display's recent errors, proxied over one connection."""
        payload = self._port.query("list_errors", {"count": count}).resolve()
        if isinstance(payload, OpError):
            return payload
        return RecentErrors.from_payload(payload)

    # -- inspection tree ----------------------------------------------------

    def _inspect(self, element: WireElement) -> InspectedElement:
        """Classify an element's render path and resolved state, then recurse."""
        render_path: Literal["abc", "legacy"] = (
            "abc" if isinstance(element, ElementABC) else "legacy"
        )
        props = (
            element.resolved_props()
            if isinstance(element, Inspectable)
            else element_to_dict(element)
        )
        children = (
            [
                self._inspect(cast("WireElement", child))
                for child in element.child_elements()
            ]
            if isinstance(element, HasChildElements)
            else []
        )
        return InspectedElement(
            id=element.id,
            kind=element.kind,
            render_path=render_path,
            resolved_props=dict(props),
            children=children,
        )

    def _mirror(self, scene_id: str) -> MirrorState:
        """Proxy the display-side mirror check as a discriminated state.

        The display answers per element under ``element_paths``; the scene-level
        answer is that EVERY element is mirrored, since a partially-mirrored scene
        is not present. A down display, a timeout, or a reply missing the paths is
        ``unavailable`` with a reason — distinct from "not requested".
        """
        payload = self._port.query("inspect_scene", {"scene_id": scene_id}).resolve()
        if isinstance(payload, OpError):
            return MirrorUnavailable(reason=payload.reason)
        paths = payload.get("element_paths")
        if not isinstance(paths, list):
            return MirrorUnavailable(reason="display reply carried no element_paths")
        entries = cast("list[object]", paths)
        present = all(
            isinstance(entry, Mapping)
            and bool(cast("Mapping[str, object]", entry).get("domain_mirror_present"))
            for entry in entries
        )
        return MirrorPresent(present=present)


@final
class _FrameAccumulator:
    """Gathers the scene ids sharing one frame while ``list_scenes`` walks."""

    _title: str
    _layout: Literal["tab", "stack"]
    _scene_ids: list[str]
    __slots__ = ("_layout", "_scene_ids", "_title")

    def __new__(cls, *, title: str, layout: Literal["tab", "stack"]) -> Self:
        self = super().__new__(cls)
        self._title = title
        self._layout = layout
        self._scene_ids = []
        return self

    def add(self, scene_id: str) -> None:
        """Record a scene shown into this frame."""
        self._scene_ids.append(scene_id)

    def summary(self, frame_id: str) -> FrameSummary:
        """Build the frame's summary once every scene is gathered."""
        return FrameSummary(
            frame_id=frame_id,
            title=self._title,
            scene_count=len(self._scene_ids),
            scene_ids=self._scene_ids,
            layout=self._layout,
        )
