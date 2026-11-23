"""Register callbacks through the client session's REST connection."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from punt_lux.client._rest_transport import _RestTransport
    from punt_lux.hub.client_identity import ClientIdentity
    from punt_lux.operations import Ok, OpError


@final
class CallbackAccessor:
    """Register callbacks delivered through the same session's listener."""

    _rest: _RestTransport
    _identity: ClientIdentity
    __slots__ = ("_identity", "_rest")

    def __new__(cls, rest: _RestTransport, identity: ClientIdentity) -> Self:
        """Bind callback registration to this transport and identity."""
        self = super().__new__(cls)
        self._rest = rest
        self._identity = identity
        return self

    async def register(
        self, callback_id: str, label: str, frame_id: str | None = None
    ) -> Ok | OpError:
        """Register a menu callback for this session.

        Args:
            frame_id: Applet-only frame to raise locally on click. Omit for
                agent callbacks that only notify the listener.
        """
        return await asyncio.to_thread(
            self._rest.register_callback, callback_id, label, frame_id
        )
