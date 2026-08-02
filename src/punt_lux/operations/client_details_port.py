"""The Details command as the Hub's interaction dispatch sees it.

A Details click lands in the domain layer, which may not call operations, so the
domain declares a port — a connection id in, an outcome out — and something in
the operations layer satisfies it. That is this class: it runs the operation and
turns its typed result into the outcome the dispatch understands, because the
dispatch cannot name an ``OpError`` and does not need to.

Details is deliberately not on the ``Operations`` facade. The facade is the
surfaces' one door, and this is not a surface capability: it is keyed by a
``ConnectionId``, a wire key no surface addresses by, and it writes a scene owned
by a connection other than the caller's. So the wiring recipe lives here, and
each composition root calls :meth:`ClientDetailsPort.for_store` and binds the
result to the dispatch.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.hub.details_outcome import DetailsRefused, DetailsShown
from punt_lux.operations.client_details import ClientDetailsOperations
from punt_lux.operations.models.common import OpError
from punt_lux.operations.queries import QueryOperations
from punt_lux.operations.scene_installer import SceneInstaller

if TYPE_CHECKING:
    from punt_lux.domain.hub.details_outcome import DetailsOutcome
    from punt_lux.domain.hub.hub import Hub
    from punt_lux.domain.hub.hub_display import HubDisplay
    from punt_lux.domain.ids import ConnectionId
    from punt_lux.operations.ports import DirtyMarker, HubPorts

__all__ = ["ClientDetailsPort"]


@final
class ClientDetailsPort:
    """Runs the Details operation and answers in the dispatch's own terms."""

    _details: ClientDetailsOperations
    __slots__ = ("_details",)

    def __new__(cls, details: ClientDetailsOperations) -> Self:
        self = super().__new__(cls)
        self._details = details
        return self

    @classmethod
    def for_store(
        cls, display: HubDisplay, replicator: DirtyMarker, *, hub: Hub, ports: HubPorts
    ) -> Self:
        """Wire the command from the collaborators the facade is wired from.

        One recipe, called by both composition roots, so a click answers from the
        same store and ports whichever root ran last. The concerns it reads
        through hold no state of their own — they are views onto ``display`` — so
        two roots building two of these is two doors onto one Hub, not two Hubs.
        """
        return cls(
            ClientDetailsOperations(
                QueryOperations(display, hub, ports.display_port),
                SceneInstaller(display, replicator),
                display.clients,
            )
        )

    def render_details(self, connection_id: ConnectionId) -> DetailsOutcome:
        """Show that connection's state, or say there was none to show."""
        shown = self._details.show_client_details(connection_id)
        refused = isinstance(shown, OpError)
        return DetailsRefused(connection_id) if refused else DetailsShown()
