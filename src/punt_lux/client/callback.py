"""``client.callback.*`` -- the Callback accessor over the REST transport.

Only ``register`` ships this cycle; ``pending()`` needs the listen-leg drain
and lands with a follow-on bead.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Self, final

from punt_lux.operations import OpError

if TYPE_CHECKING:
    from punt_lux.client._rest_transport import _RestTransport
    from punt_lux.domain.hub.client_identity import ClientIdentity
    from punt_lux.operations import Ok
    from punt_lux.operations.models.callbacks import RegisterCallbackRequest


@final
class CallbackAccessor:
    """The ``client.callback.*`` verbs; takes a request like every other accessor."""

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
        """Register a menu callback for this session; ``frame_id`` is applet-only."""
        return (
            request
            if isinstance(request, OpError)
            else await asyncio.to_thread(
                self._rest.register_callback, *request.rest_args()
            )
        )
