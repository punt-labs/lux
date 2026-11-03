"""HubClientRegistry — the Hub sessions, each with its connect time, identity, lease.

The one identity store, keyed by ``ConnectionId`` and serialized by ``_lock``.
Each session carries a lease; the live read (:meth:`live_sessions`) filters to
sessions still in lease without removing anyone — a read changes nothing here.
Departure is the province of ``ClientLifecycle``'s single atomic
deregister-and-release step, which reaps through the write surface — one lock
hold that finds and removes the lapsed set together, so a renewal racing in
between can't be evicted anyway. The clock is injected for deterministic tests.

The registry is the read side. Every write -- record, renew, discard, reap, and the
listen leg with its callbacks -- is presence, and is made under this same lock
through the :class:`PresenceWrites` that :meth:`take_writes` hands, once, to the
lifecycle.

The menu names live here too, reached only under this lock, so a name is
assigned only to a session live at that instant and released only by the
step that removes it.
"""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.hub.client_roster import ClientRoster
from punt_lux.domain.hub.client_session import ClientSession
from punt_lux.domain.hub.named_sessions import NamedSessions
from punt_lux.domain.hub.presence_writes import PresenceWrites

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from punt_lux.domain.hub.client_identity import ClientIdentity
    from punt_lux.domain.ids import ConnectionId

__all__ = ["HubClientRegistry"]


@final
class HubClientRegistry:
    """The registered Hub sessions, keyed by ``ConnectionId`` to their session."""

    _sessions: dict[ConnectionId, ClientSession]
    _roster: ClientRoster
    _lock: threading.Lock
    _clock: Callable[[], float]
    _writes_taken: bool
    __slots__ = ("_clock", "_lock", "_roster", "_sessions", "_writes_taken")

    def __new__(cls, clock: Callable[[], float] = time.monotonic) -> Self:
        self = super().__new__(cls)
        self._sessions = {}
        self._roster = ClientRoster()
        self._lock = threading.Lock()
        self._clock = clock
        self._writes_taken = False
        return self

    def take_writes(self) -> PresenceWrites:
        """Hand over the write surface, once, to the lifecycle.

        Every write to a session is presence: it owes the Hub a mark and a sink,
        which only ``ClientLifecycle`` pays. So the surface is given away exactly
        once, to it; no one else can reach it through the registry.
        """
        if self._writes_taken:
            msg = "the presence writes were already handed to a lifecycle"
            raise ValueError(msg)
        self._writes_taken = True
        return PresenceWrites(
            self._sessions, self._roster.take_release(), self._lock, self._clock
        )

    def session_of(self, connection_id: ConnectionId) -> ClientSession | None:
        """Return the connection's raw session, or ``None``, with no lease filter."""
        with self._lock:
            return self._sessions.get(connection_id)

    def identity_of(self, connection_id: ConnectionId) -> ClientIdentity | None:
        """The identity the connection declared; None if unregistered or anonymous."""
        with self._lock:
            session = self._sessions.get(connection_id)
        return None if session is None else session.identity

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

    def _live_locked(self) -> dict[ConnectionId, ClientSession]:
        """The sessions whose lease has not lapsed, as of now. Caller locks."""
        now = self._clock()
        return dict(filter(lambda kv: kv[1].is_live(now), self._sessions.items()))
