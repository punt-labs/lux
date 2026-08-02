"""luxd's ``/ws`` route: resolve who is connecting, then serve their session.

The listen leg's front door. Every connection declares its identity in the same
``X-Lux-Client-*`` headers REST uses, so the two legs of one client resolve to a
single connection id and a callback registered over REST is delivered on this
socket. An unidentified or malformed handshake is refused rather than served an
anonymous session: a listen leg owns a session, and only a named client may.

Serving that session is :class:`~punt_lux.ws_listen.HubListenSession`'s job; this
module only decides who is asking and hands the socket over.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Self, final

from pydantic import ValidationError
from starlette.websockets import WebSocket

from punt_lux.connection_identity import connection_for
from punt_lux.domain.hub import hub, hub_display
from punt_lux.domain.hub.client_identity import ClientIdentity
from punt_lux.domain.hub.replicator_instance import (
    hub_callback_router,
    hub_replicator,
)
from punt_lux.identity_headers import ClientHeaders
from punt_lux.ws_listen import HubListenSession

if TYPE_CHECKING:
    from fastapi import FastAPI

    from punt_lux.domain.hub.callback_hold import CallbackRouter
    from punt_lux.domain.hub.hub import Hub
    from punt_lux.domain.hub.hub_clients import HubClientRegistry
    from punt_lux.operations.ports import DirtyMarker

logger = logging.getLogger(__name__)

__all__ = ["WS_PATH", "HubListenTransport"]

WS_PATH = "/ws"

# A client that declares no identity in its handshake headers is refused: a listen
# leg owns a session, and only a named client may. 1008 is the WebSocket policy code.
_POLICY_VIOLATION = 1008


@final
class HubListenTransport:
    """Mounts ``/ws`` and builds a :class:`HubListenSession` per connection."""

    _hub: Hub
    _clients: HubClientRegistry
    _router: CallbackRouter
    _menus: DirtyMarker
    __slots__ = ("_clients", "_hub", "_menus", "_router")

    def __new__(
        cls,
        hub: Hub,
        clients: HubClientRegistry,
        router: CallbackRouter,
        menus: DirtyMarker,
    ) -> Self:
        self = super().__new__(cls)
        self._hub = hub
        self._clients = clients
        self._router = router
        self._menus = menus
        return self

    @classmethod
    def for_hub(cls) -> Self:
        """Wire the transport over the Hub's process singletons."""
        return cls(hub, hub_display.clients, hub_callback_router, hub_replicator)

    def mount(self, app: FastAPI) -> None:
        """Add the ``/ws`` WebSocket route to the parent app."""
        app.add_api_websocket_route(WS_PATH, self._endpoint, name="listen")

    async def _endpoint(self, websocket: WebSocket) -> None:
        """Resolve the client's identity from the handshake, then serve its session.

        The identity rides the ``X-Lux-Client-*`` handshake headers exactly as it
        does on REST, and the connection is derived from the same declaration dict
        (:func:`connection_for`), so the two legs resolve to one shared id. An
        unidentified or malformed handshake is refused with a policy-violation close
        rather than served an anonymous session.
        """
        declaration = ClientHeaders.declaration_from(websocket.headers)
        identity = self._identity_of(declaration)
        if declaration is None or identity is None:
            await websocket.close(code=_POLICY_VIOLATION)
            return
        conn = connection_for(declaration)
        session = HubListenSession(
            websocket,
            conn,
            identity,
            self._hub,
            self._clients,
            self._router,
            self._menus,
        )
        await session.run()

    @staticmethod
    def _identity_of(declaration: dict[str, object] | None) -> ClientIdentity | None:
        """Validate a handshake declaration into an identity, or ``None`` if unusable.

        A wire boundary: an unnamed handshake (``declaration`` is ``None``), or one
        whose identity fields are garbled, is refused the leg — the absence is the
        documented outcome, not a raised error that would crash the connection.
        """
        if declaration is None:
            return None
        try:
            return ClientIdentity.model_validate(declaration)
        except ValidationError:
            logger.info("listen handshake declared a malformed identity; refusing")
            return None
