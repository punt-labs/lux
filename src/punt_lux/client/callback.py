"""``client.callback.*`` -- the Callback accessor over the REST transport.

Only ``register`` ships in this cycle. ``client.callback.pending()`` requires
the listen-leg drain (see :class:`~punt_lux.commands._ports.CallbackPendingOps`
-- "No REST route exists or can exist for this read; delivery is the listen
leg's drain, which only the in-process ``Operations`` facade can serve"), so
it lands with a follow-on bead that either wires it through the WebSocket
listener or grows an in-process transport variant.
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
    already validates and posts. Wiring it through the singleton is bead
    ``lux-0shg.7-follow-on``. ``frame_id`` is applet-only -- it names the frame a
    click should raise Display-locally, before the click reaches the Hub; agents
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
