"""PresenceWrites — every write to the registry's sessions, under the registry's lock.

A session's record, its lease, its listen leg and its menu callbacks decide who the
Clients menu lists, so each write owes the Hub a mark and a bound sink -- paid only
by ``ClientLifecycle``. The registry therefore hands this write surface away exactly
once, to the lifecycle (:meth:`HubClientRegistry.take_writes`), and keeps only reads.

One connection is shared by successive sessions of one identity, so a leg write is a
compare against the session occupying the slot: :meth:`attach`,
:meth:`register_callback`, and :meth:`detach` each make that compare-and-write one
critical section. The sessions, the roster and the lock are the registry's own,
shared by reference, so these writes and the registry's reads are serialized together.
"""

from __future__ import annotations

import threading
from collections import deque
from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.hub.leg_writes import Detachment, Registration
from punt_lux.domain.hub.reaped import Reaped
from punt_lux.domain.hub.session_write import SessionWrite

if TYPE_CHECKING:
    from collections.abc import Callable

    from punt_lux.client_host import ClientHost
    from punt_lux.domain.hub.callback_ports import CallbackListener
    from punt_lux.domain.hub.client_identity import ClientIdentity
    from punt_lux.domain.hub.client_roster import ClientRoster
    from punt_lux.domain.hub.client_session import ClientSession
    from punt_lux.domain.hub.session_callback import SessionCallback
    from punt_lux.domain.hub.session_write import Attachment
    from punt_lux.domain.ids import ConnectionId

__all__ = ["PresenceWrites"]


@final
class PresenceWrites:
    """Record, renew, discard, reap, and seat the registry's sessions."""

    _sessions: dict[ConnectionId, ClientSession]
    _roster: ClientRoster
    _lock: threading.Lock
    _clock: Callable[[], float]
    __slots__ = ("_clock", "_lock", "_roster", "_sessions")

    def __new__(
        cls,
        sessions: dict[ConnectionId, ClientSession],
        roster: ClientRoster,
        lock: threading.Lock,
        clock: Callable[[], float],
    ) -> Self:
        self = super().__new__(cls)
        self._sessions = sessions
        self._roster = roster
        self._lock = lock
        self._clock = clock
        return self

    def record(
        self,
        connection_id: ConnectionId,
        identity: ClientIdentity | None,
        host: ClientHost,
    ) -> SessionWrite:
        """Upsert the connection's session, renewing its lease and any identity.

        Any contact is a renewal: an existing session keeps its connect time
        and pushes its lease forward. The first call stamps the connect time.
        Returns the write, so the caller can read what it did to the menu and
        whether it named the connection.
        """
        with self._lock:
            write = SessionWrite.recorded(
                self._sessions.get(connection_id), self._clock(), identity, host
            )
            self._sessions[connection_id] = write.after
            return write

    def renew_if_registered(
        self, connection_id: ConnectionId, host: ClientHost
    ) -> SessionWrite | None:
        """Renew the lease iff already registered; a write must never register.

        The contact's ``host`` is recorded on the session it renews. ``None`` is
        a connection the registry does not hold: nothing was written.
        """
        with self._lock:
            before = self._sessions.get(connection_id)
            if before is None:
                return None
            write = SessionWrite.recorded(before, self._clock(), None, host)
            self._sessions[connection_id] = write.after
            return write

    def discard(self, connection_id: ConnectionId) -> frozenset[ConnectionId]:
        """Drop the registration, its identity, and the menu name it held.

        Returns the survivors whose name the release moved.
        """
        with self._lock:
            self._sessions.pop(connection_id, None)
            return self._roster.release((connection_id,))

    def reap_lapsed(self, exclude: frozenset[ConnectionId] = frozenset()) -> Reaped:
        """Atomically find-and-remove every lapsed connection except ``exclude``.

        One lock hold: a renewal cannot slip between the find and the remove.
        """
        with self._lock:
            now = self._clock()
            lapsed = (
                frozenset(
                    cid
                    for cid, session in self._sessions.items()
                    if not session.is_live(now)
                )
                - exclude
            )
            deque(map(self._sessions.pop, lapsed), maxlen=0)
            return Reaped(lapsed, self._roster.release(lapsed))

    def attach(
        self,
        connection_id: ConnectionId,
        identity: ClientIdentity,
        listener: CallbackListener,
        host: ClientHost,
    ) -> Attachment:
        """Install ``listener`` as the connection's leg, recording ``identity``.

        Records and takes the slot in one step; taking it clears the previous
        occupant's callbacks and reports ``attached_over_callbacks``, alongside how
        the write changed who the Clients menu lists.
        """
        with self._lock:
            write = SessionWrite.recorded(
                self._sessions.get(connection_id), self._clock(), identity, host
            ).seated(listener)
            self._sessions[connection_id] = write.after
            return write.attachment

    def detach(
        self, connection_id: ConnectionId, listener: CallbackListener
    ) -> Detachment:
        """Release the slot and its callbacks if ``listener`` still holds it.

        One critical section: a session superseded while suspended is
        genuinely ``kept``, but one the lease sweep already took is not. A
        release is returned with the write that made it, so the caller can settle
        what the withdrawal owes the Display.
        """
        with self._lock:
            session = self._sessions.get(connection_id)
            if session is None:
                return Detachment("released_with_session")
            released = session.detached(listener)
            if released is None:
                return Detachment("kept")
            self._sessions[connection_id] = released
            write = SessionWrite(session, released, self._clock())
            if session.callbacks:
                return Detachment("released_with_callbacks", write)
            return Detachment("released", write)

    def register_callback(
        self,
        connection_id: ConnectionId,
        callback: SessionCallback,
        expected: CallbackListener,
    ) -> Registration:
        """Register ``callback`` if ``expected`` still holds the connection's slot.

        The gate and the write are one critical section; the session itself
        decides whether it accepts -- an anonymous or lapsed one declines. A
        registration that took is returned with the write that made it.
        """
        with self._lock:
            now = self._clock()
            session = self._sessions.get(connection_id)
            if session is None or not session.held_by(expected):
                return Registration("superseded")
            updated = session.registering(callback, now)
            if updated is None:
                return Registration("declined")
            self._sessions[connection_id] = updated
            return Registration("registered", SessionWrite(session, updated, now))

    def listener_for(self, connection_id: ConnectionId) -> CallbackListener | None:
        """The connection's listen leg, or ``None`` when it holds none."""
        with self._lock:
            session = self._sessions.get(connection_id)
            return session.listener if session is not None else None
