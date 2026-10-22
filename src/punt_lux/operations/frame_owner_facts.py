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

from punt_lux.domain.hub.frame_ownership import FrameOwnership
from punt_lux.operations.client_identity_facts import ClientIdentityFacts
from punt_lux.operations.client_listing import ClientListing

if TYPE_CHECKING:
    from punt_lux.domain.hub.hub import Hub
    from punt_lux.domain.hub.hub_clients import HubClientRegistry
    from punt_lux.domain.hub.hub_display import HubDisplay
    from punt_lux.domain.ids import SceneId
    from punt_lux.operations.ports import HubPorts

__all__ = ["FrameOwnerFacts"]


@final
class FrameOwnerFacts:
    """Resolve one scene's senior owner into the popup's field/value rows."""

    _display: HubDisplay
    _clients: ClientListing
    __slots__ = ("_clients", "_display")

    def __new__(cls, display: HubDisplay, clients: ClientListing) -> Self:
        self = super().__new__(cls)
        self._display = display
        self._clients = clients
        return self

    @classmethod
    def for_store(
        cls,
        display: HubDisplay,
        clients: HubClientRegistry,
        *,
        hub: Hub,
        ports: HubPorts,
    ) -> Self:
        """Wire the reader from the collaborators the facade is wired from.

        Mirrors :meth:`ClientDetailsPort.for_store` — the composition root hands
        over the same primitives (the store, the Hub, the port bundle) and this
        builds its own ``ClientListing``/``QueryOperations``, so a composition
        root doesn't need those two imports just to bind this one reader.
        """
        return cls(display, ClientListing(display, clients, hub, ports.inbox_depth))

    def facts_for(self, scene_id: SceneId) -> FrameOwnership:
        """Return the senior owner's rows and scope label, empty if unowned.

        The senior owner is the scene's first-appearance root owner
        (``HubDisplay.scene_owners``). A connection the roster no longer holds a
        live session for (a departure raced this read) reports the empty
        ownership too; the display keeps what it last held rather than blanking.
        Rows and label come from the one ``named`` read, so they cannot
        disagree.
        """
        owners = self._display.scene_owners(scene_id)
        if not owners:
            return FrameOwnership()
        named = self._clients.named(owners[0].connection_id)
        if named is None:
            return FrameOwnership()
        client = self._clients.facts(named)
        rows = ClientIdentityFacts(client, named.name).build().rows()
        return FrameOwnership(rows, named.scope_label)
