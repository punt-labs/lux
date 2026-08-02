"""QueryOperations — the read surface, Hub-authoritative where it can be.

``inspect_scene``, ``list_scenes``, and ``list_clients`` read the authoritative
Hub state directly: the element store, its presentations, and the session
registry. This is the reach-around removal — asking the authority, not the
display replica. ``list_recent_events`` and ``list_errors`` are facts about the
running display's own ring buffers, so they proxy over luxd's one connection.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Self, cast, final

from punt_lux.domain.ids import SceneId
from punt_lux.operations.display_facts import DisplayFactProxy
from punt_lux.operations.frame_grouping import FrameAccumulator
from punt_lux.operations.models.common import OpError
from punt_lux.operations.models.inspect_scope import HUB_ONLY, InspectScope
from punt_lux.operations.models.query_clients import ClientList, HubClient
from punt_lux.operations.models.query_errors import RecentErrors
from punt_lux.operations.models.query_events import RecentEvents
from punt_lux.operations.models.query_inspection import (
    InspectedElement,
    SceneInspection,
)
from punt_lux.operations.models.query_ownership import SceneOwner
from punt_lux.operations.models.query_scenes import SceneList, SceneSummary

if TYPE_CHECKING:
    from punt_lux.domain.hub.client_session import ClientSession
    from punt_lux.domain.hub.hub import Hub
    from punt_lux.domain.hub.hub_display import HubDisplay
    from punt_lux.domain.ids import ConnectionId
    from punt_lux.operations.display_port import DisplayPort
    from punt_lux.protocol import Element as WireElement

__all__ = ["QueryOperations"]


@final
class QueryOperations:
    """Answer read queries from the Hub, proxying only the display's own facts."""

    _display: HubDisplay
    _hub: Hub
    _port: DisplayPort
    _facts: DisplayFactProxy
    __slots__ = ("_display", "_facts", "_hub", "_port")

    def __new__(cls, display: HubDisplay, hub: Hub, port: DisplayPort) -> Self:
        self = super().__new__(cls)
        self._display = display
        self._hub = hub
        self._port = port
        self._facts = DisplayFactProxy(display, port)
        return self

    # -- Hub-authoritative reads -------------------------------------------

    def inspect_scene(
        self, scene_id: str, scope: InspectScope = HUB_ONLY
    ) -> SceneInspection | OpError:
        """Return a scene's element tree read from the authoritative store.

        Reads ``HubDisplay`` — never the display replica. An unknown scene is a
        ``not_found``. The display-side mirror check and painted geometry are
        proxied only when ``scope`` asks and are never treated as Hub authority.
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
        mirror, geometry = self._facts.facts(scene_id, scope)
        return SceneInspection(
            scene_id=scene_id, elements=elements, mirror=mirror, geometry=geometry
        )

    def list_scenes(self) -> SceneList:
        """List every live scene and frame from the authoritative store."""
        scenes: list[SceneSummary] = []
        frames: dict[str, FrameAccumulator] = {}
        for sid in self._display.live_scene_ids():
            presentation = self._display.frames.presentation_for(sid)
            scenes.append(
                SceneSummary(
                    scene_id=str(sid),
                    element_count=self._display.element_count(sid),
                    frame_id=presentation.frame_id,
                    owners=self._owners_of(sid),
                )
            )
            layout = presentation.frame_layout or "tab"
            frame = frames.setdefault(
                presentation.frame_id,
                FrameAccumulator(
                    title=presentation.frame_title or presentation.frame_id,
                    layout=layout,
                ),
            )
            frame.add(str(sid))
        return SceneList(
            scenes=scenes,
            frames=[acc.summary(fid) for fid, acc in frames.items()],
        )

    def list_clients(self) -> ClientList:
        """List the Hub's sessions with the identity each declared and its age.

        Ages come off the monotonic clock the sessions were stamped with, so
        ``connected_seconds`` never goes negative under a wall-clock step.
        """
        now = time.monotonic()
        return ClientList(
            clients=[
                self._client(connection_id, session, now)
                for connection_id, session in self._display.client_sessions().items()
            ]
        )

    def client_of(self, connection_id: ConnectionId) -> HubClient | OpError:
        """Return one session's facts, or ``not_found`` when the Hub holds none.

        The same read ``list_clients`` reports, narrowed to one connection — what
        the Details command renders, so the menu and the introspection read can
        never describe a client differently.
        """
        session = self._display.client_sessions().get(connection_id)
        if session is None:
            return OpError(
                code="not_found",
                reason=f"no client is connected as {connection_id!s}",
            )
        return self._client(connection_id, session, time.monotonic())

    def _client(
        self, connection_id: ConnectionId, session: ClientSession, now: float
    ) -> HubClient:
        """Build one session's read shape from the authoritative Hub state."""
        return HubClient(
            connection_id=str(connection_id),
            identity=session.identity,
            connected_seconds=round(session.age(now), 1),
            lease_ttl_seconds=session.lease_ttl_seconds,
            subscribed_topics=sorted(
                str(topic) for topic in self._hub.topics_for(connection_id)
            ),
            owned_scenes=sorted(
                {str(s) for s, _ in self._display.elements_owned_by(connection_id)}
            ),
        )

    def _owners_of(self, scene_id: SceneId) -> list[SceneOwner]:
        """Return the scene's distinct owners as introspection read shapes."""
        return [SceneOwner.of(owner) for owner in self._display.scene_owners(scene_id)]

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
        """Return an element's resolved state and recurse into its children.

        Every kind is on the Element-ABC path, so ``render_path`` is always
        ``"abc"`` and every element resolves its own props and exposes its
        children.
        """
        children = [
            self._inspect(cast("WireElement", child))
            for child in element.child_elements()
        ]
        return InspectedElement(
            id=element.id,
            kind=element.kind,
            render_path="abc",
            resolved_props=dict(element.resolved_props()),
            children=children,
        )
