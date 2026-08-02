"""ClientDetailsOperations — show one client's connection state as a scene.

The Hub's own menu command. Every client's submenu carries ``Details``, and the
Hub answers it itself rather than routing it to the client, because what it
reports is the Hub's own record of that connection — the same record
``list_clients`` returns, narrowed to one client and rendered.

The scene is owned by the client it describes, so it appears among that client's
scenes and goes when that client's scenes are cleared; and it is shown into a
frame of its own per client, so opening the details of two clients puts two
frames side by side rather than one that keeps changing under the reader.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.hub.scene_presentation import ScenePresentation
from punt_lux.operations.models.common import OpError
from punt_lux.operations.scope import Scope
from punt_lux.operations.timing import Timed
from punt_lux.protocol.compositions.client_details import (
    ClientDetails,
    ClientDetailsComposition,
)

if TYPE_CHECKING:
    from punt_lux.domain.hub.hub_clients import HubClientRegistry
    from punt_lux.domain.ids import ConnectionId
    from punt_lux.operations.models.query_clients import HubClient
    from punt_lux.operations.models.scene_results import SceneShown
    from punt_lux.operations.queries import QueryOperations
    from punt_lux.operations.scenes import SceneOperations

__all__ = ["ClientDetailsOperations"]

# The scene and frame one client's details are shown in. Per client, so two can
# be read at once; stable per client, so asking twice repaints in place.
_SCENE_PREFIX = "lux.client-details"

# What a client with no menu name yet is called — one the Hub holds a session
# for but that registered nothing, so the roster never named it.
_UNNAMED = "client"


@final
class ClientDetailsOperations:
    """Render the Hub's own record of one connection into that client's scene."""

    _queries: QueryOperations
    _scenes: SceneOperations
    _clients: HubClientRegistry
    __slots__ = ("_clients", "_queries", "_scenes")

    def __new__(
        cls,
        queries: QueryOperations,
        scenes: SceneOperations,
        clients: HubClientRegistry,
    ) -> Self:
        self = super().__new__(cls)
        self._queries = queries
        self._scenes = scenes
        self._clients = clients
        return self

    @Timed("show_client_details")
    def show_client_details(self, connection_id: ConnectionId) -> SceneShown | OpError:
        """Show one client's connection state, or say why there is nothing to show.

        A click can outlive its client — the menu is a replica, and a lease may
        lapse between the paint and the pointer — so a connection the Hub no
        longer holds is a ``not_found``, never a blank scene.
        """
        client = self._queries.client_of(connection_id)
        if isinstance(client, OpError):
            return client
        details = self._details(connection_id, client)
        table = ClientDetailsComposition.build(
            details, element_id=f"{_SCENE_PREFIX}.table"
        )
        return self._scenes.install(
            table,
            scene_id=self._scene_id(connection_id),
            presentation=self._presentation(connection_id, details.label),
            ttl_seconds=None,  # a details frame stays until the user closes it
            scope=Scope(connection_id),
        )

    def _details(self, connection_id: ConnectionId, client: HubClient) -> ClientDetails:
        """Turn one client's read shape into the facts the scene reports."""
        identity = client.identity
        return ClientDetails(
            label=self._label(connection_id),
            connection_id=client.connection_id,
            kind=identity.kind if identity is not None else "unidentified",
            name=identity.name if identity is not None else _UNNAMED,
            repo=identity.repo if identity is not None else None,
            agent=identity.agent if identity is not None else None,
            connected_seconds=client.connected_seconds,
            lease=client.lease,
            subscribed_topics=tuple(client.subscribed_topics),
            owned_scenes=tuple(client.owned_scenes),
        )

    def _label(self, connection_id: ConnectionId) -> str:
        """The name the menu calls this client, so the frame agrees with the menu.

        Read from the one roster the menu assigns from. A client whose entry the
        user just clicked is always in it; the fallback covers the click that
        arrives after its client has gone.
        """
        return self._clients.roster.held().get(connection_id, _UNNAMED)

    @staticmethod
    def _scene_id(connection_id: ConnectionId) -> str:
        """The scene one client's details are always shown in."""
        return f"{_SCENE_PREFIX}.{connection_id}"

    @classmethod
    def _presentation(
        cls, connection_id: ConnectionId, label: str
    ) -> ScenePresentation:
        """Show the details in their own frame, titled for the client they describe."""
        scene_id = cls._scene_id(connection_id)
        return ScenePresentation(
            frame_id=scene_id,
            title=f"{label} — client details",
            frame_title=f"{label} — client details",
            frame_size=(560, 340),
        )
