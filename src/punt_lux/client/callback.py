"""``client.callback.*`` -- the Callback accessor over the REST transport.

Only ``register`` ships in this cycle; ``pending()`` needs the listen-leg
drain (:class:`~punt_lux.commands._ports.CallbackPendingOps`) and lands with
a follow-on bead wiring it through the WebSocket listener.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from punt_lux.client._rest_transport import _RestTransport
    from punt_lux.domain.hub.client_identity import ClientIdentity
    from punt_lux.operations import Ok, OpError


@final
class CallbackAccessor:
    """The ``client.callback.*`` verbs -- ``register`` this cycle.

    ``register`` reaches REST directly rather than the
    :mod:`punt_lux.commands.callback_register` singleton because the transport
    already validates and posts (bead ``lux-0shg.7-follow-on``). ``frame_id``
    is applet-only, naming the frame a click raises Display-locally; agents
    never pass it.
    """

    _rest: _RestTransport
    _identity: ClientIdentity
    __slots__ = ("_identity", "_rest")

    def __new__(cls, rest: _RestTransport, identity: ClientIdentity) -> Self:
        self = super().__new__(cls)
        self._rest = rest
        self._identity = identity
        return self

    async def register(
        self, callback_id: str, label: str, frame_id: str | None = None
    ) -> Ok | OpError:
        """Register a menu callback for this session."""
        return await asyncio.to_thread(
            self._rest.register_callback, callback_id, label, frame_id
        )
