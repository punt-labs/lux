"""HubClientRegistry — the Hub sessions, each with its connect time, identity, lease.

The one identity store, keyed by ``ConnectionId`` and serialized by ``_lock``.
Each session carries a lease; any recorded contact renews it, and the live reads
(:meth:`live_sessions`, :meth:`repos`) return only sessions still in lease,
sweeping the lapsed as they pass so a departed caller cannot accrue forever. The
clock is injected so a test can drive expiry deterministically.
"""

from __future__ import annotations

import threading
import time
from operator import attrgetter
from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.hub.client_session import ClientSession
from punt_lux.domain.ids import ConnectionId

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from punt_lux.domain.hub.client_identity import ClientIdentity
    from punt_lux.domain.hub.session_callback import SessionCallback

__all__ = ["HubClientRegistry"]


@final
class HubClientRegistry:
    """The registered Hub sessions, keyed by ``ConnectionId`` to their session."""

    _sessions: dict[ConnectionId, ClientSession]
    _lock: threading.Lock
    _clock: Callable[[], float]
    __slots__ = ("_clock", "_lock", "_sessions")

    def __new__(cls, clock: Callable[[], float] = time.monotonic) -> Self:
        self = super().__new__(cls)
        self._sessions = {}
        self._lock = threading.Lock()
        self._clock = clock
        return self

    def record(
        self, connection_id: ConnectionId, identity: ClientIdentity | None = None
    ) -> None:
        """Upsert the connection's session, renewing its lease and any given identity.

        Any contact is a renewal: an existing session keeps its connect time and
        pushes its lease forward, and a declared identity resets the lease to its
        kind's length. The first call stamps the monotonic connect time.
        """
        with self._lock:
            now = self._clock()
            existing = self._sessions.get(connection_id)
            base = existing.renewed(now) if existing is not None else ClientSession(now)
            self._sessions[connection_id] = (
                base.with_identity(identity) if identity is not None else base
            )

    def register_callback(
        self, connection_id: ConnectionId, callback: SessionCallback
    ) -> bool:
        """Register ``callback`` on an identified live session; report whether it took.

        The callback lives on the session, so this is one guarded upsert under the
        registry's own lock — the same lock ``record`` and the live reads hold, so
        withdrawal on a lapsed lease needs no second lock and cannot race the sweep.
        The session itself decides whether it accepts the callback (``registering``
        returns ``None`` from an unknown, unidentified, or lapsed session); the
        registry stores the returned session or leaves the store untouched, and the
        caller turns a ``False`` into an identify challenge.
        """
        with self._lock:
            now = self._clock()
            session = self._sessions.get(connection_id)
            updated = None if session is None else session.registering(callback, now)
            self._sessions.update(
                {connection_id: updated} if updated is not None else {}
            )
            return updated is not None

    def session_of(self, connection_id: ConnectionId) -> ClientSession | None:
        """Return the connection's raw session, or ``None``, with no lease filter.

        The read behind membership (``is not None``) and identity (``.identity``);
        ownership and cleanup address a session by its bare connection key.
        """
        with self._lock:
            return self._sessions.get(connection_id)

    def discard(self, connection_id: ConnectionId) -> None:
        """Drop the registration and its identity. No-op if absent."""
        with self._lock:
            self._sessions.pop(connection_id, None)

    def sessions(self) -> Mapping[ConnectionId, ClientSession]:
        """Return every recorded session, live or lapsed, without sweeping."""
        with self._lock:
            return dict(self._sessions)

    def live_sessions(self) -> Mapping[ConnectionId, ClientSession]:
        """Return the sessions whose lease has not lapsed, sweeping the expired.

        The opportunistic reap: each live read rebuilds the store keeping only the
        in-lease sessions, so no timer thread is needed — introspection and menu
        reads pass through often enough to bound accrual.
        """
        with self._lock:
            now = self._clock()
            survivors = filter(lambda kv: kv[1].is_live(now), self._sessions.items())
            self._sessions = dict(survivors)
            return dict(self._sessions)

    def repos(self) -> frozenset[str]:
        """Return the distinct repositories the live identified sessions declared."""
        declared = map(attrgetter("declared_repo"), self.live_sessions().values())
        return frozenset(filter(None, declared))
