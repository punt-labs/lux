"""QueryOperations — the read surface, Hub-authoritative where it can be.

``inspect_scene``, ``list_scenes``, and ``list_clients`` read the authoritative
Hub state directly: the element store, its presentations, and the session
registry. This is the reach-around removal — asking the authority, not the
display replica. ``list_recent_events`` and ``list_errors`` are facts about the
running display's own ring buffers, so they proxy over luxd's one connection.

Scene-summary grouping lives in :class:`~punt_lux.operations.scene_listing.SceneListing`
and client-session facts in :class:`~punt_lux.operations.client_listing.ClientListing`
(DES-065 OO paydown) — each is its own reason to change. This facade wires
them to the one Hub connection every read shares, and owns directly the two
concerns that don't fit either: the inspection tree and the two proxied
display-fact reads.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, cast, final

from punt_lux.domain.hub.connection_scoped_id import ConnectionScopedId
from punt_lux.domain.ids import SceneId
from punt_lux.operations.client_listing import ClientListing
from punt_lux.operations.composition_boundary import CompositionBoundary
from punt_lux.operations.display_facts import DisplayFactProxy
from punt_lux.operations.frame_visibility_proxy import FrameVisibilityProxy
from punt_lux.operations.models.common import OpError
from punt_lux.operations.models.inspect_scope import HUB_ONLY, InspectScope
from punt_lux.operations.models.query_clients import ClientList, HubClient
from punt_lux.operations.models.query_errors import RecentErrors
from punt_lux.operations.models.query_events import RecentEvents
from punt_lux.operations.models.query_inspection import (
    InspectedElement,
    SceneInspection,
)
from punt_lux.operations.models.query_scenes import SceneList
from punt_lux.operations.scene_listing import SceneListing

if TYPE_CHECKING:
    from punt_lux.domain.hub.hub import Hub
    from punt_lux.domain.hub.hub_display import HubDisplay
    from punt_lux.domain.hub.named_sessions import NamedSession
    from punt_lux.operations.display_port import DisplayPort
    from punt_lux.operations.scope import Scope
    from punt_lux.protocol import Element as WireElement

__all__ = ["QueryOperations"]


@final
class QueryOperations:
    """Answer read queries from the Hub, proxying only the display's own facts."""

    _display: HubDisplay
    _port: DisplayPort
    _facts: DisplayFactProxy
    _scenes: SceneListing
    _clients: ClientListing
    __slots__ = ("_clients", "_display", "_facts", "_port", "_scenes")

    def __new__(cls, display: HubDisplay, hub: Hub, port: DisplayPort) -> Self:
        self = super().__new__(cls)
        self._display = display
        self._port = port
        self._facts = DisplayFactProxy(port)
        self._scenes = SceneListing(display, FrameVisibilityProxy(port))
        self._clients = ClientListing(display, hub)
        return self

    # -- Hub-authoritative reads -------------------------------------------

    def inspect_scene(
        self, scene_id: str, scope: Scope, facts: InspectScope = HUB_ONLY
    ) -> SceneInspection | OpError:
        """Return a scene's element tree read from the authoritative store.

        Reads ``HubDisplay`` — never the display replica. ``scene_id`` is
        composed against the caller's own connection before the lookup, the
        same way ``update``/``clear`` compose their own targets — a caller can
        only ever inspect a scene it owns, with no override (DES-086,
        Decision 5: "you can only inspect what you put into the
        hub/display"). An unknown or unowned scene is a ``not_found``, never
        distinguished from each other — the composed key either resolves to a
        scene this caller installed, or it resolves to nothing at all. The
        display-side painted geometry is proxied only when ``facts`` asks and
        is never treated as Hub authority.
        """
        sid = CompositionBoundary.compose_or_reject(
            lambda: SceneId(ConnectionScopedId.compose(scope.connection_id, scene_id))
        )
        if isinstance(sid, OpError):
            return sid
        if sid not in self._display.all_scene_ids():
            return OpError(code="not_found", reason=f"scene {scene_id!r} not found")
        # The store hands back domain elements; they are structurally the wire
        # Element the codec and the ABC checks read (PY-TS-12 domain/wire bridge).
        elements = [
            self._inspect(cast("WireElement", root))
            for root in self._display.scene_roots(sid)
        ]
        geometry = self._facts.facts(str(sid), facts)
        return SceneInspection(
            scene_id=scene_id,
            elements=elements,
            geometry=geometry,
            quarantine=self._scenes.quarantine_info(sid),
        )

    def list_scenes(self, facts: InspectScope = HUB_ONLY) -> SceneList:
        """List every scene and frame from the authoritative store.

        Delegates the grouping and summarizing to
        :class:`~punt_lux.operations.scene_listing.SceneListing`; see its
        :meth:`~punt_lux.operations.scene_listing.SceneListing.read` for the
        quarantine and frame-visibility contract.
        """
        return self._scenes.read(facts)

    def list_clients(self) -> ClientList:
        """List the Hub's sessions with the identity each declared and its age.

        Delegates to :class:`~punt_lux.operations.client_listing.ClientListing`.
        """
        return self._clients.read()

    def client_facts(self, named: NamedSession) -> HubClient:
        """Return one session's facts — the shape ``list_clients`` reports, for one.

        Delegates to :class:`~punt_lux.operations.client_listing.ClientListing`,
        what the Details command renders.
        """
        return self._clients.facts(named)

    @staticmethod
    def local_id_of(scene_id: SceneId | str) -> str:
        """Return the caller's own label for a store key, composed or not.

        Delegates to :class:`~punt_lux.operations.scene_listing.SceneListing`,
        which every scene-summary read already shares this label with.
        """
        return SceneListing.local_id_of(scene_id)

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
        """Return an element's resolved state and recurse into its children."""
        children = [
            self._inspect(cast("WireElement", child))
            for child in element.child_elements()
        ]
        return InspectedElement(
            id=element.id,
            kind=element.kind,
            resolved_props=dict(element.resolved_props()),
            children=children,
        )
