"""QueryOperations — the read surface, Hub-authoritative where it can be.

``inspect_scene``, ``list_scenes``, and ``list_clients`` read the authoritative
Hub state directly: the element store, its presentations, and the session
registry. This is the reach-around removal — asking the authority, not the
display replica. ``list_recent_events`` and ``list_errors`` are facts about the
running display's own ring buffers, so they proxy over luxd's one connection.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Self, cast, final

from punt_lux.domain.hub.connection_scoped_id import ConnectionScopedId
from punt_lux.domain.ids import SceneId
from punt_lux.operations.composition_boundary import CompositionBoundary
from punt_lux.operations.display_facts import DisplayFactProxy
from punt_lux.operations.frame_grouping import FrameAccumulator
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
from punt_lux.operations.models.query_ownership import SceneOwner
from punt_lux.operations.models.query_quarantine import QuarantineInfo
from punt_lux.operations.models.query_scenes import (
    FrameSummary,
    SceneList,
    SceneSummary,
)

if TYPE_CHECKING:
    from punt_lux.domain.hub.client_session import ClientSession
    from punt_lux.domain.hub.hub import Hub
    from punt_lux.domain.hub.hub_display import HubDisplay
    from punt_lux.domain.hub.named_sessions import NamedSession
    from punt_lux.domain.hub.quarantine_record import QuarantineRecord
    from punt_lux.domain.hub.scene_presentation import ScenePresentation
    from punt_lux.domain.ids import ConnectionId
    from punt_lux.operations.display_port import DisplayPort
    from punt_lux.operations.scope import Scope
    from punt_lux.protocol import Element as WireElement

__all__ = ["QueryOperations"]

logger = logging.getLogger(__name__)


@final
class QueryOperations:
    """Answer read queries from the Hub, proxying only the display's own facts."""

    _display: HubDisplay
    _hub: Hub
    _port: DisplayPort
    _facts: DisplayFactProxy
    _seen: FrameVisibilityProxy
    __slots__ = ("_display", "_facts", "_hub", "_port", "_seen")

    def __new__(cls, display: HubDisplay, hub: Hub, port: DisplayPort) -> Self:
        self = super().__new__(cls)
        self._display = display
        self._hub = hub
        self._port = port
        self._facts = DisplayFactProxy(port)
        self._seen = FrameVisibilityProxy(port)
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
            quarantine=self._quarantine_info(sid),
        )

    def list_scenes(self, facts: InspectScope = HUB_ONLY) -> SceneList:
        """List every scene and frame from the authoritative store.

        Includes quarantined scenes alongside live ones — quarantine is a
        replication decision, not a deletion, so introspection stays honest
        about the scenes the store still holds. Each summary carries a
        ``status`` discriminator (``"live"`` or ``"quarantined"``) and, when
        quarantined, the :class:`QuarantineInfo` record explaining why.
        Replication reads through :meth:`HubDisplay.live_scene_ids` instead,
        which excludes quarantined scenes at the source.

        ``facts`` may ask for each frame's visibility, which is the one thing
        here the Hub does not hold: where a window sits belongs to the user and
        is never replicated back (DES-088). It is proxied from the running
        display only when asked, so a bare call stays a single Hub-local read and
        never reaches around — the same bargain ``inspect_scene`` strikes for
        painted geometry.
        """
        scenes: list[SceneSummary] = []
        frames: dict[str, FrameAccumulator] = {}
        for sid in self._display.all_scene_ids():
            presentation = self._display.frames.presentation_for(sid)
            scenes.append(self._scene_summary(sid, presentation))
            self._gather(frames, presentation).add(str(sid))
        return SceneList(scenes=scenes, frames=self._frame_summaries(frames, facts))

    def _scene_summary(
        self, sid: SceneId, presentation: ScenePresentation
    ) -> SceneSummary:
        """Build one scene's summary, quarantined or live."""
        quarantine = self._quarantine_info(sid)
        return SceneSummary(
            scene_id=str(sid),
            local_id=self.local_id_of(sid),
            element_count=self._display.element_count(sid),
            frame_id=presentation.frame_id,
            owners=self._owners_of(sid),
            status="quarantined" if quarantine is not None else "live",
            quarantine=quarantine,
        )

    @staticmethod
    def _gather(
        frames: dict[str, FrameAccumulator], presentation: ScenePresentation
    ) -> FrameAccumulator:
        """Return the accumulator for this scene's frame, starting one if needed."""
        return frames.setdefault(
            presentation.frame_id,
            FrameAccumulator(
                title=presentation.frame_title or presentation.frame_id,
                layout=presentation.frame_layout or "tab",
            ),
        )

    def _frame_summaries(
        self, frames: dict[str, FrameAccumulator], facts: InspectScope
    ) -> list[FrameSummary]:
        """Close every accumulator, attaching the visibility ``facts`` asked for.

        The display is asked once for the whole call rather than once per frame:
        asking repeatedly would let the answer change mid-list.
        """
        seen = self._seen.of_frames(facts)
        absent = self._seen.absent(facts)
        return [acc.summary(fid, seen.get(fid, absent)) for fid, acc in frames.items()]

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

    def client_facts(self, named: NamedSession) -> HubClient:
        """Return one session's facts — the shape ``list_clients`` reports, for one.

        What the Details command renders, so the menu and introspection agree.
        Reads the session the caller already holds rather than re-reading the
        registry, which sweeps lapsed sessions and could retire this client.
        """
        return self._client(named.connection_id, named.session, time.monotonic())

    def _client(
        self, connection_id: ConnectionId, session: ClientSession, now: float
    ) -> HubClient:
        """Build one session's read shape from the authoritative Hub state.

        ``owned_scenes`` is stripped to each caller's own local id here, at
        the introspection boundary — the same composed store key
        ``inspect_scene``/``update``/``clear`` require callers to compose
        themselves. Reporting the raw composed key would hand an agent a
        value that separator-rejects on every write path that takes it back.
        """
        return HubClient(
            connection_id=str(connection_id),
            identity=session.identity,
            connected_seconds=round(session.age(now), 1),
            lease=session.lease_term,
            subscribed_topics=sorted(
                str(topic) for topic in self._hub.topics_for(connection_id)
            ),
            owned_scenes=sorted(
                {
                    self.local_id_of(s)
                    for s, _ in self._display.elements_owned_by(connection_id)
                }
            ),
        )

    @staticmethod
    def local_id_of(scene_id: SceneId | str) -> str:
        """Return the caller's own label for a store key, composed or not.

        Every scene the ops-layer write path installs is composed (DES-086),
        so this is the caller's raw name in the common case. A key installed
        through a lower-level API directly carries no separator at all; it is
        reported as-is rather than raising, but logged — a DES-086 invariant
        violation worth knowing about, not silently absorbed.
        """
        try:
            return ConnectionScopedId.from_composed(str(scene_id)).local_id
        except ValueError:
            logger.warning("non-composed store key at introspection: %r", scene_id)
            return str(scene_id)

    def _owners_of(self, scene_id: SceneId) -> list[SceneOwner]:
        """Return the scene's distinct owners as introspection read shapes."""
        return [SceneOwner.of(owner) for owner in self._display.scene_owners(scene_id)]

    def _quarantine_info(self, scene_id: SceneId) -> QuarantineInfo | None:
        """Return the scene's quarantine read shape, or None if not quarantined."""
        record: QuarantineRecord | None = self._display.quarantine_record(scene_id)
        if record is None:
            return None
        return QuarantineInfo.of(record)

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
