"""ClientDetailsOperations — show one client's connection state as a scene.

The Hub's own menu command. Every client's submenu carries ``Details``, and the
Hub answers it itself rather than routing it to the client, because what it
reports is the Hub's own record of that connection — the same record
``list_clients`` returns, narrowed to one client and rendered by
:class:`~punt_lux.operations.details_scene.DetailsScene`.

The scene is owned by the client it describes, so it appears among that client's
scenes and goes when that client's scenes are cleared. That ownership is
attribution, not contact: the client is not the one calling. So this operation
holds the plain ``SceneInstaller`` rather than the caller-scoped
``SceneOperations``, and cannot register anybody — a Details frame never brings
back a session the Hub has let go of.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.hub.named_sessions import NamedSession
from punt_lux.operations.details_scene import DetailsScene
from punt_lux.operations.models.common import OpError
from punt_lux.operations.timing import Timed

if TYPE_CHECKING:
    from punt_lux.domain.hub.hub_clients import HubClientRegistry
    from punt_lux.domain.ids import ConnectionId
    from punt_lux.operations.models.scene_results import SceneShown
    from punt_lux.operations.queries import QueryOperations
    from punt_lux.operations.scene_installer import SceneInstaller

__all__ = ["ClientDetailsOperations"]

# What the frame calls a client the menu never named — one the Hub holds a
# session for but that declared no identity, so the roster passed it over.
_UNNAMED = "client"


@final
class ClientDetailsOperations:
    """Render the Hub's own record of one connection into that client's scene."""

    _queries: QueryOperations
    _installer: SceneInstaller
    _clients: HubClientRegistry
    __slots__ = ("_clients", "_installer", "_queries")

    def __new__(
        cls,
        queries: QueryOperations,
        installer: SceneInstaller,
        clients: HubClientRegistry,
    ) -> Self:
        self = super().__new__(cls)
        self._queries = queries
        self._installer = installer
        self._clients = clients
        return self

    @Timed("show_client_details")
    def show_client_details(self, connection_id: ConnectionId) -> SceneShown | OpError:
        """Show one client's connection state, or say why there is nothing to show.

        A click can outlive its client — the menu is a replica, and a lease may
        lapse between the paint and the pointer — so a connection the Hub no
        longer holds is a ``not_found``, never a blank scene. One read of the
        roster settles which of the two happened; see :meth:`_named`.
        """
        named = self._named(connection_id)
        return (
            self._shown(named) if named is not None else self._no_client(connection_id)
        )

    def _named(self, connection_id: ConnectionId) -> NamedSession | None:
        """Take one read of the roster and what it says about this connection.

        The read the menu is composed from, so the frame and the bar agree, and it
        yields both answers at once — whether the Hub still holds this client, and
        what it calls it. ``None`` is the departed client: the connection held no
        session at that instant, this read possibly being what swept it.
        """
        live = self._clients.named_sessions()
        session = live.sessions.get(connection_id)
        name = live.name_of(connection_id, _UNNAMED)
        return None if session is None else NamedSession(connection_id, name, session)

    def _shown(self, named: NamedSession) -> SceneShown | OpError:
        """Install this client's details as the scene that client owns."""
        scene = DetailsScene(self._queries.client_facts(named), named.name)
        return self._installer.install(scene.submission(), owner=named.connection_id)

    @staticmethod
    def _no_client(connection_id: ConnectionId) -> OpError:
        """Say the Hub holds no session for that connection, so nothing was shown."""
        return OpError(
            code="not_found", reason=f"no client is connected as {connection_id!s}"
        )
