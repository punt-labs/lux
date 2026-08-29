"""ClientListing — build the session facts ``list_clients`` and Details report.

Split out of ``queries`` (DES-065 OO paydown): reading the Hub's session
registry into introspection shapes is one cohesive concern, distinct from
summarizing scenes and frames
(:class:`~punt_lux.operations.scene_listing.SceneListing`) or walking one
scene's element tree (``QueryOperations._inspect``).
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Self, final

from punt_lux.operations.models.query_clients import ClientList, HubClient
from punt_lux.operations.scene_listing import SceneListing

if TYPE_CHECKING:
    from punt_lux.domain.hub.client_session import ClientSession
    from punt_lux.domain.hub.hub import Hub
    from punt_lux.domain.hub.hub_display import HubDisplay
    from punt_lux.domain.hub.named_sessions import NamedSession
    from punt_lux.domain.ids import ConnectionId

__all__ = ["ClientListing"]


@final
class ClientListing:
    """Every connected client's facts, read from the authoritative session registry."""

    _display: HubDisplay
    _hub: Hub
    __slots__ = ("_display", "_hub")

    def __new__(cls, display: HubDisplay, hub: Hub) -> Self:
        self = super().__new__(cls)
        self._display = display
        self._hub = hub
        return self

    def read(self) -> ClientList:
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

    def facts(self, named: NamedSession) -> HubClient:
        """Return one session's facts — the shape :meth:`list` reports, for one.

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
                    SceneListing.local_id_of(s)
                    for s, _ in self._display.elements_owned_by(connection_id)
                }
            ),
        )
