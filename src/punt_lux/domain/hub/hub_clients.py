"""HubClientRegistry — the Hub sessions, each with its connect time, identity, lease.

The one identity store, keyed by ``ConnectionId`` and serialized by ``_lock``.
Each session carries a lease; any recorded contact renews it, and the live reads
(:meth:`live_sessions`, :meth:`repos`) return only sessions still in lease,
sweeping the lapsed as they pass so a departed caller cannot accrue forever. The
clock is injected so a test can drive expiry deterministically.

The registry also holds each connection's listen leg, because the leg and the
callbacks registered against it must be written under one lock. One connection is
shared by successive sessions of one identity, so every write to that state is a
compare against the session occupying the slot: :meth:`attach_listener` installs a
new occupant and clears what the last one owned, :meth:`register_callback` commits
only if the leg the caller was gated against still holds the slot, and
:meth:`detach_listener` removes nothing unless the caller is the occupant. Each is one
critical section; a comparison that is not atomic with its write is the gap it closes.

The menu names live here for the same reason: the roster is private to this
registry and reached only under this lock, so a name is assigned only to a
session live at that instant and released only by the step that removes it.
"""

from __future__ import annotations

import threading
import time
from operator import attrgetter
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
        """Upsert the connection's session, renewing its lease and any given identity.

        Any contact is a renewal: an existing session keeps its connect time and
        pushes its lease forward, and a declared identity resets the lease to its
        kind's length. The first call stamps the monotonic connect time.
        """
        with self._lock:
            base = self._renewed(connection_id)
            self._sessions[connection_id] = (
                base.with_identity(identity) if identity is not None else base
            )

    def attach_listener(
        self,
        connection_id: ConnectionId,
        identity: ClientIdentity,
        listener: CallbackListener,
    ) -> ListenerAttachment:
        """Install ``listener`` as the connection's leg, recording ``identity`` with it.

        Records and takes the slot in one step, so no thread ever sees it
        identified-but-unreachable or reachable-but-anonymous. Taking the slot
        clears the previous occupant's callbacks — deliverable only to a leg
        it no longer holds — and tells the caller so via
        ``attached_over_callbacks``, since nothing else is guaranteed to
        correct a bar left showing a now-dead entry.
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

        The comparison and the removal are one critical section. A session
        superseded while suspended is genuinely ``kept`` — a successor holds
        the connection and the bar is right — but a session the lease sweep
        already took is not: nobody holds the connection, and calling that
        ``kept`` too would leave the sweep's orphan entries on screen.
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

        The caller reads the leg through :meth:`listener_of` to decide what to tell
        an unreachable connection, and hands that leg back here; between those two
        moments the leg may have torn down or been replaced, and committing anyway
        would leave an entry with no listener and nothing left that would ever
        withdraw it. The slot and the callbacks are one value under this lock, so the
        comparison and the write are one critical section, not a re-read that races.

        The session itself decides whether it accepts the callback at all — an
        anonymous or lapsed session declines — so identity and lease stay its own.
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
        """The connection's listen leg, or ``None`` when it holds none.

        The registration gate's read. ``None`` is the real state of a connection
        that reached the Hub over a one-shot call rather than a held leg, so the
        caller can name the requirement instead of guessing at a failure.
        """
        with self._lock:
            session = self._sessions.get(connection_id)
            return session.listener if session is not None else None

    def session_of(self, connection_id: ConnectionId) -> ClientSession | None:
        """Return the connection's raw session, or ``None``, with no lease filter.

        The read behind membership (``is not None``) and identity (``.identity``);
        ownership and cleanup address a session by its bare connection key.
        """
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

        The reap and the naming of the survivors are one critical section.
        """
        with self._lock:
            self._sweep_locked()
            return NamedSessions.over(self._sessions, self._roster)

    def live_sessions(self) -> Mapping[ConnectionId, ClientSession]:
        """Return the sessions whose lease has not lapsed, sweeping the expired."""
        return self.named_sessions().sessions

    def reap(self) -> frozenset[ConnectionId]:
        """Sweep out every lapsed session; return who left, not who stayed."""
        with self._lock:
            return self._sweep_locked()

    def repos(self) -> frozenset[str]:
        """Return the distinct repositories the live identified sessions declared."""
        declared = map(attrgetter("declared_repo"), self.live_sessions().values())
        return frozenset(filter(None, declared))

    def _sweep_locked(self) -> frozenset[ConnectionId]:
        """Drop every lapsed session and its name; return what left. Caller locks."""
        now = self._clock()
        live = dict(filter(lambda kv: kv[1].is_live(now), self._sessions.items()))
        reaped = frozenset(self._sessions.keys() - live.keys())
        self._roster.release(reaped)
        self._sessions = live
        return reaped

    def _renewed(self, connection_id: ConnectionId) -> ClientSession:
        """The connection's session, renewed now, or a fresh one; caller locks.

        Every contact starts here, so arriving is one concept with one
        implementation rather than a rule each entry point has to remember.
        """
        now = self._clock()
        existing = self._sessions.get(connection_id)
        return existing.renewed(now) if existing is not None else ClientSession(now)
