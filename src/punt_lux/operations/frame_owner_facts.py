"""FrameOwnerFacts — the operations-layer reader for a scene's owner facts.

Satisfies :class:`~punt_lux.domain.hub.frame_owner_facts.FrameOwnerFactsReader`
structurally: the replicator's scene-send path is domain code, so it declares
the port it needs and this class answers it, reusing the Details command's
own facts and formatting
(:class:`~punt_lux.operations.client_identity_facts.ClientIdentityFacts`,
:class:`~punt_lux.protocol.compositions.client_details.ClientDetails`) so the
popup and the Hub's own record of a connection always agree.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.hub.named_sessions import NamedSession
from punt_lux.operations.client_identity_facts import ClientIdentityFacts
from punt_lux.operations.client_listing import ClientListing
from punt_lux.operations.queries import QueryOperations

if TYPE_CHECKING:
    from punt_lux.domain.hub.hub import Hub
    from punt_lux.domain.hub.hub_display import HubDisplay
    from punt_lux.domain.ids import ConnectionId, SceneId
    from punt_lux.operations.ports import HubPorts

__all__ = ["FrameOwnerFacts"]

# What the popup calls a client the roster never named -- one the Hub holds a
# session for but that declared no identity (mirrors ClientDetailsOperations).
_UNNAMED = "client"


@final
class FrameOwnerFacts:
    """Resolve one scene's senior owner into the popup's field/value rows."""

    _display: HubDisplay
    _queries: QueryOperations
    __slots__ = ("_display", "_queries")

    def __new__(cls, display: HubDisplay, queries: QueryOperations) -> Self:
        self = super().__new__(cls)
        self._display = display
        self._queries = queries
        return self

    @classmethod
    def for_store(cls, display: HubDisplay, *, hub: Hub, ports: HubPorts) -> Self:
        """Wire the reader from the collaborators the facade is wired from.

        Mirrors :meth:`ClientDetailsPort.for_store` — the composition root hands
        over the same primitives (the store, the Hub, the port bundle) and this
        builds its own ``ClientListing``/``QueryOperations``, so a composition
        root doesn't need those two imports just to bind this one reader.
        """
        clients = ClientListing(display, hub, ports.inbox_depth)
        return cls(display, QueryOperations(display, ports.display_port, clients))

    def facts_for(self, scene_id: SceneId) -> tuple[tuple[str, str], ...] | None:
        """Return the senior owner's rows, or ``None`` if unowned or departed.

        The senior owner is the scene's first-appearance root owner
        (``HubDisplay.scene_owners``) -- the same convention the Clients menu's
        Details command points at. A connection the roster no longer holds a
        live session for (a departure raced this read) reports ``None`` too;
        the display keeps its last cached snapshot rather than blanking it.
        """
        owners = self._display.scene_owners(scene_id)
        if not owners:
            return None
        named = self._named(owners[0].connection_id)
        if named is None:
            return None
        client = self._queries.client_facts(named)
        return ClientIdentityFacts(client, named.name).build().rows()

    def _named(self, connection_id: ConnectionId) -> NamedSession | None:
        """Read one connection's live session and menu name together, or ``None``."""
        live = self._display.clients.named_sessions()
        session = live.sessions.get(connection_id)
        name = live.name_of(connection_id, _UNNAMED)
        return None if session is None else NamedSession(connection_id, name, session)
