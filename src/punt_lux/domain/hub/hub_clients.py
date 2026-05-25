"""HubClientRegistry — set of ``ConnectionId`` registered as Hub clients.

A connection becomes a client when the transport binds it via the
inbox-init path; it is removed when the connection drops. The registry
is what ``Display.interact`` ultimately consults to refuse traffic from
an unknown or disconnected client.

Distinct from ``ClientRegistry`` in ``clients.py``, which owns the
``DisplayClient`` and reconnect policy on the rendering process side.
"""

from __future__ import annotations

from typing import Self

from punt_lux.domain.ids import ConnectionId

__all__ = ["HubClientRegistry"]


class HubClientRegistry:
    """Set of currently-registered Hub client ``ConnectionId``s."""

    _registered: set[ConnectionId]

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._registered = set()
        return self

    def register(self, connection_id: ConnectionId) -> None:
        """Mark ``connection_id`` as a known client. Idempotent."""
        self._registered.add(connection_id)

    def is_registered(self, connection_id: ConnectionId) -> bool:
        """Return whether ``connection_id`` is currently registered."""
        return connection_id in self._registered

    def discard(self, connection_id: ConnectionId) -> None:
        """Drop the registration. No-op if absent."""
        self._registered.discard(connection_id)
