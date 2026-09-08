"""HubClientRegistry — the Hub sessions, each with its connect time, identity, lease.

The one identity store, keyed by ``ConnectionId`` and serialized by ``_lock``.
Each session carries a lease; the live reads (:meth:`live_sessions`,
:meth:`repos`) filter to sessions still in lease without removing anyone —
a read changes nothing here. Departure is the province of ``HubDisplay``'s
single atomic deregister-and-release coordinator, which reaches
:meth:`reap_lapsed_locked` — one lock hold that finds and removes the lapsed
set together, so a renewal racing in between can't be evicted anyway. The
clock is injected for deterministic tests.

The registry also holds each connection's listen leg, so the leg and its
callbacks are written under this same lock. One connection is shared by
successive sessions of one identity, so every write is a compare against the
session occupying the slot: :meth:`attach_listener`, :meth:`register_callback`,
and :meth:`detach_listener` each make that compare-and-write one critical
section.

The menu names live here too, reached only under this lock, so a name is
assigned only to a session live at that instant and released only by the
step that removes it.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from operator import attrgetter, itemgetter
from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.hub.client_roster import ClientRoster
from punt_lux.domain.hub.client_session import ClientSession
from punt_lux.domain.hub.named_sessions import NamedSessions
from punt_lux.domain.hub.registry_outcomes import (
    CallbackRegistration,
    ListenerAttachment,
    ListenerDetachment,
)
from punt_lux.domain.ids import ConnectionId

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from punt_lux.domain.hub.callback_ports import CallbackListener
    from punt_lux.domain.hub.client_identity import ClientIdentity
    from punt_lux.domain.hub.session_callback import SessionCallback

__all__ = ["HubClientRegistry"]


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

    def record(
        self, connection_id: ConnectionId, identity: ClientIdentity | None = None
    ) -> None:
        """Upsert the connection's session, renewing its lease and any identity.

        Any contact is a renewal: an existing session keeps its connect time
        and pushes its lease forward. The first call stamps the connect time.
        """
        with self._lock:
            base = self._renewed(connection_id)
            self._sessions[connection_id] = (
                base.with_identity(identity) if identity is not None else base
            )

    def renew_if_registered(self, connection_id: ConnectionId) -> None:
        """Renew the lease iff already registered; a write must never register."""
        with self._lock:
            existing = self._sessions.get(connection_id)
            # Merging an empty update is a true no-op -- never a `None`-valued
            # insert -- so "renew" and "absent" are one write, not a branch.
            renewed = None if existing is None else existing.renewed(self._clock())
            self._sessions.update({connection_id: renewed} if renewed else {})

    def attach_listener(
        self,
        connection_id: ConnectionId,
        identity: ClientIdentity,
        listener: CallbackListener,
    ) -> ListenerAttachment:
        """Install ``listener`` as the connection's leg, recording ``identity``.

        Records and takes the slot in one step; taking it clears the previous
        occupant's callbacks and reports ``attached_over_callbacks``.
        """
        with self._lock:
            base = self._renewed(connection_id)
            self._sessions[connection_id] = base.with_identity(identity).attached(
                listener
            )
            return "attached_over_callbacks" if base.callbacks else "attached"

    def detach_listener(
        self, connection_id: ConnectionId, listener: CallbackListener
    ) -> ListenerDetachment:
        """Release the slot and its callbacks if ``listener`` still holds it.

        One critical section: a session superseded while suspended is
        genuinely ``kept``, but one the lease sweep already took is not.
        """
        with self._lock:
            session = self._sessions.get(connection_id)
            if session is None:
                return "released_with_session"
            released = session.detached(listener)
            if released is None:
                return "kept"
            self._sessions[connection_id] = released
            return "released_with_callbacks" if session.callbacks else "released"

    def register_callback(
        self,
        connection_id: ConnectionId,
        callback: SessionCallback,
        expected: CallbackListener,
    ) -> CallbackRegistration:
        """Register ``callback`` if ``expected`` still holds the connection's slot.

        The gate and the write are one critical section; the session itself
        decides whether it accepts -- an anonymous or lapsed one declines.
        """
        with self._lock:
            now = self._clock()
            session = self._sessions.get(connection_id)
            if session is None or not session.held_by(expected):
                return "superseded"
            updated = session.registering(callback, now)
            if updated is None:
                return "declined"
            self._sessions[connection_id] = updated
            return "registered"

    def listener_of(self, connection_id: ConnectionId) -> CallbackListener | None:
        """The connection's listen leg, or ``None`` when it holds none."""
        with self._lock:
            session = self._sessions.get(connection_id)
            return session.listener if session is not None else None

    def session_of(self, connection_id: ConnectionId) -> ClientSession | None:
        """Return the connection's raw session, or ``None``, with no lease filter."""
        with self._lock:
            return self._sessions.get(connection_id)

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

        One lock hold, not two -- a renewal racing between a separate compute
        and a separate discard would otherwise still get evicted.
        """
        with self._lock:
            lapsed = self._lapsed_locked() - exclude
            deque(map(self._sessions.pop, lapsed), maxlen=0)
            self._roster.release(lapsed)
            return lapsed

    def repos(self) -> frozenset[str]:
        """Return the distinct repositories the live identified sessions declared."""
        declared = map(attrgetter("declared_repo"), self.live_sessions().values())
        return frozenset(filter(None, declared))

    def _live_locked(self) -> dict[ConnectionId, ClientSession]:
        """The sessions whose lease has not lapsed, as of now. Caller locks."""
        now = self._clock()
        return dict(filter(lambda kv: kv[1].is_live(now), self._sessions.items()))

    def _lapsed_locked(self) -> frozenset[ConnectionId]:
        """Every registered connection whose lease has lapsed. Caller locks."""
        now = self._clock()
        stale = filter(lambda kv: not kv[1].is_live(now), self._sessions.items())
        return frozenset(map(itemgetter(0), stale))

    def _renewed(self, connection_id: ConnectionId) -> ClientSession:
        """The connection's session, renewed now, or a fresh one; caller locks."""
        now = self._clock()
        existing = self._sessions.get(connection_id)
        return existing.renewed(now) if existing is not None else ClientSession(now)
