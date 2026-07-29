"""HubClientRegistry — the Hub sessions, each with its connect time and identity.

The Hub's own session roster, keyed by ``ConnectionId``: when each client
connected and the identity it declared. It is the one identity store — the menu
capability model's live repository set is :meth:`repos`, a read over it, not a
second store. Every access is serialized by ``_lock``, which guards only the dict.
"""

from __future__ import annotations

import threading
import time
from operator import attrgetter
from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.hub.client_identity import ClientSession
from punt_lux.domain.ids import ConnectionId

if TYPE_CHECKING:
    from collections.abc import Mapping

    from punt_lux.domain.hub.client_identity import ClientIdentity

__all__ = ["HubClientRegistry"]


@final
class HubClientRegistry:
    """The registered Hub sessions, keyed by ``ConnectionId`` to their session."""

    _sessions: dict[ConnectionId, ClientSession]
    _lock: threading.Lock
    __slots__ = ("_lock", "_sessions")

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._sessions = {}
        self._lock = threading.Lock()
        return self

    def record(
        self, connection_id: ConnectionId, identity: ClientIdentity | None = None
    ) -> None:
        """Upsert the connection's session, recording a declared identity if given.

        Idempotent: the first call stamps the monotonic connect time; a later call
        keeps it, so age never resets and re-recording without an identity never
        drops one already declared.
        """
        with self._lock:
            base = self._sessions.get(connection_id, ClientSession(time.monotonic()))
            self._sessions[connection_id] = (
                base.with_identity(identity) if identity is not None else base
            )

    def discard(self, connection_id: ConnectionId) -> None:
        """Drop the registration and its identity. No-op if absent."""
        with self._lock:
            self._sessions.pop(connection_id, None)

    def sessions(self) -> Mapping[ConnectionId, ClientSession]:
        """Return each registered connection paired with its session record."""
        with self._lock:
            return dict(self._sessions)

    def repos(self) -> frozenset[str]:
        """Return the distinct repositories the identified sessions declared."""
        with self._lock:
            declared = map(attrgetter("declared_repo"), self._sessions.values())
            return frozenset(filter(None, declared))
