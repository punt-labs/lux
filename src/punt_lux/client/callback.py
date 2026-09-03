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
    from punt_lux.operations.models.callbacks import RegisterCallbackRequest


@final
class CallbackAccessor:
    """The ``client.callback.*`` verbs -- ``register`` this cycle.

    Reaches REST directly (bead ``lux-0shg.7-follow-on``), not the
    :mod:`punt_lux.commands.callback_register` singleton. Takes a request
    object like every other accessor -- unlike the transport's bare-args
    ``CallbackConvenienceOps`` kept for ``applets/leg.py``.
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
        self, request: RegisterCallbackRequest | OpError
    ) -> Ok | OpError:
        """Register a menu callback for this session; ``frame_id`` is applet-only.

        Forwards an invalid ``request`` unchecked; see :meth:`_RestTransport.register`.
        """
        return await asyncio.to_thread(self._rest.register, request)
