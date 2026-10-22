"""HubClientRegistry — the Hub sessions, each with its connect time, identity, lease.

The one identity store, keyed by ``ConnectionId`` and serialized by ``_lock``.
Each session carries a lease; the live read (:meth:`live_sessions`) filters to
sessions still in lease without removing anyone — a read changes nothing here.
Departure is the province of ``ClientLifecycle``'s single atomic
deregister-and-release step, which reaches :meth:`reap_lapsed_locked` — one lock
hold that finds and removes the lapsed set together, so a renewal racing in
between can't be evicted anyway. The clock is injected for deterministic tests.

The registry also holds each connection's listen leg, so the leg and its
callbacks are written under this same lock, through :attr:`legs`.

The menu names live here too, reached only under this lock, so a name is
assigned only to a session live at that instant and released only by the
step that removes it.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.hub.client_roster import ClientRoster
from punt_lux.domain.hub.client_session import ClientSession
from punt_lux.domain.hub.listener_legs import ListenerLegs
from punt_lux.domain.hub.named_sessions import NamedSessions
from punt_lux.domain.hub.session_write import SessionWrite

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from punt_lux.domain.hub.client_identity import ClientIdentity
    from punt_lux.domain.hub.menu_listing import PresenceChange
    from punt_lux.domain.ids import ConnectionId

__all__ = ["HubClientRegistry"]


_ANONYMOUS = ClientSession(0.0)  # a connection with no session has declared nothing


@final
class HubClientRegistry:
    """The registered Hub sessions, keyed by ``ConnectionId`` to their session."""

    _sessions: dict[ConnectionId, ClientSession]
    _roster: ClientRoster
    _lock: threading.Lock
    _clock: Callable[[], float]
    __slots__ = ("_clock", "_lock", "_roster", "_sessions")

    def __new__(cls, clock: Callable[[], float] = time.monotonic) -> Self:
        self = super().__new__(cls)
        self._sessions = {}
        self._roster = ClientRoster()
        self._lock = threading.Lock()
        self._clock = clock
        return self

    @property
    def legs(self) -> ListenerLegs:
        """A view of the connections' listener slots, under this registry's lock."""
        return ListenerLegs(self._sessions, self._lock, self._clock)

    def record(
        self, connection_id: ConnectionId, identity: ClientIdentity | None = None
    ) -> PresenceChange:
        """Upsert the connection's session, renewing its lease and any identity.

        Any contact is a renewal: an existing session keeps its connect time
        and pushes its lease forward. The first call stamps the connect time.
        """
        with self._lock:
            write = SessionWrite.recorded(
                self._sessions.get(connection_id), self._clock(), identity
            )
            self._sessions[connection_id] = write.after
            return write.presence

    def renew_if_registered(self, connection_id: ConnectionId) -> PresenceChange:
        """Renew the lease iff already registered; a write must never register."""
        with self._lock:
            before = self._sessions.get(connection_id)
            write = SessionWrite.recorded(before, self._clock(), None)
            # An absent connection stays absent: an empty update is a true no-op.
            self._sessions.update(
                {} if before is None else {connection_id: write.after}
            )
            return write.presence

    def session_of(self, connection_id: ConnectionId) -> ClientSession | None:
        """Return the connection's raw session, or ``None``, with no lease filter."""
        with self._lock:
            return self._sessions.get(connection_id)

    def identity_of(self, connection_id: ConnectionId) -> ClientIdentity | None:
        """The identity the connection declared; None if unregistered or anonymous."""
        return self._sessions.get(connection_id, _ANONYMOUS).identity

    def discard(self, connection_id: ConnectionId) -> None:
        """Drop the registration, its identity, and the menu name it held."""
        with self._lock:
            self._sessions.pop(connection_id, None)
            self._roster.release((connection_id,))

    def sessions(self) -> Mapping[ConnectionId, ClientSession]:
        """Return every recorded session, live or lapsed, without sweeping."""
        with self._lock:
            return dict(self._sessions)

    def named_sessions(self) -> NamedSessions:
        """Return the live sessions and the menu name each identified one holds.

        A pure read: filters to the live set, removing nobody from the registry.
        """
        with self._lock:
            return NamedSessions.over(self._live_locked(), self._roster)

    def live_sessions(self) -> Mapping[ConnectionId, ClientSession]:
        """Return the sessions whose lease has not lapsed. Sweeps no one."""
        return self.named_sessions().sessions

    def reap_lapsed_locked(
        self, exclude: frozenset[ConnectionId] = frozenset()
    ) -> frozenset[ConnectionId]:
        """Atomically find-and-remove every lapsed connection except ``exclude``.

        One lock hold: a renewal cannot slip between the find and the remove.
        """
        with self._lock:
            lapsed = self._lapsed_locked() - exclude
            deque(map(self._sessions.pop, lapsed), maxlen=0)
            self._roster.release(lapsed)
            return lapsed

    def _live_locked(self) -> dict[ConnectionId, ClientSession]:
        """The sessions whose lease has not lapsed, as of now. Caller locks."""
        now = self._clock()
        return dict(filter(lambda kv: kv[1].is_live(now), self._sessions.items()))

    def _lapsed_locked(self) -> frozenset[ConnectionId]:
        """Every registered connection whose lease has lapsed. Caller locks."""
        return frozenset(self._sessions) - self._live_locked().keys()
