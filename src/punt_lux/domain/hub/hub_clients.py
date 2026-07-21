"""HubClientRegistry — the Hub sessions, each with the time it first connected.

A connection becomes a client when the transport binds it via the inbox-init
path; it is removed when the connection drops. This registry is the Hub's own
session roster — the meaningful answer to "which clients are connected", now that
the display has exactly one socket client (luxd). Each session records the wall
clock at which it first registered, so ``list_clients`` can report its age.

Distinct from ``ClientRegistry`` in ``clients.py``, which owns the
``DisplayClient`` and reconnect policy on the rendering process side.
"""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.ids import ConnectionId

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ["HubClientRegistry"]


@final
class HubClientRegistry:
    """The registered Hub sessions, keyed by ``ConnectionId`` to connect time.

    Bind and unbind run on connection threads while ``list_clients`` reads on a
    tool thread, so every access to the roster is serialized by ``_lock``. The
    lock guards only the dict; nothing is called out to while it is held.
    """

    _connected_at: dict[ConnectionId, float]
    _lock: threading.Lock
    __slots__ = ("_connected_at", "_lock")

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._connected_at = {}
        self._lock = threading.Lock()
        return self

    def register(self, connection_id: ConnectionId) -> None:
        """Mark ``connection_id`` as a known client. Idempotent.

        The first registration stamps the connect time; a later re-register keeps
        it, so a session's reported age never resets under normal traffic.
        """
        with self._lock:
            self._connected_at.setdefault(connection_id, time.time())

    def is_registered(self, connection_id: ConnectionId) -> bool:
        """Return whether ``connection_id`` is currently registered."""
        with self._lock:
            return connection_id in self._connected_at

    def discard(self, connection_id: ConnectionId) -> None:
        """Drop the registration. No-op if absent."""
        with self._lock:
            self._connected_at.pop(connection_id, None)

    def sessions(self) -> Mapping[ConnectionId, float]:
        """Return each registered connection paired with its connect time."""
        with self._lock:
            return dict(self._connected_at)
