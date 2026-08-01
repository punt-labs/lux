"""HubClientRegistry — the Hub sessions, each with its connect time, identity, lease.

The one identity store, keyed by ``ConnectionId`` and serialized by ``_lock``.
Each session carries a lease; any recorded contact renews it, and the live reads
(:meth:`live_sessions`, :meth:`repos`) return only sessions still in lease,
sweeping the lapsed as they pass so a departed caller cannot accrue forever. The
clock is injected so a test can drive expiry deterministically.

The registry also holds each connection's listen leg, because the leg and the
callbacks registered against it must be written under one lock. One connection is
shared by successive sessions of one identity, so every write to that state is a
compare against the session occupying the slot: :meth:`attach_listener` installs
a new occupant and clears what the last one owned, :meth:`register_callback`
commits only if the leg the caller was gated against still holds the slot, and
:meth:`detach_listener` removes nothing unless the caller is the occupant. Each
is one critical section; a comparison that is not atomic with its write is the
gap it exists to close.
"""

from __future__ import annotations

import threading
import time
from operator import attrgetter
from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.hub.client_session import ClientSession
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

        A connecting session records itself and takes the slot in one step, so no
        thread can see it identified but unreachable, or reachable but anonymous.
        Taking the slot clears the callbacks the previous occupant owned: they were
        deliverable only to it, and it has lost the connection they were registered
        on. The arriving app re-registers from its connect hook.

        Whether entries were cleared is the caller's, because clearing them is what
        makes the bar wrong. The events that would correct it are not guaranteed —
        the arriving app may register nothing, and a click on a dead entry only
        finds the fault rather than fixing it — so the caller marks the menu on
        ``attached_over_callbacks`` and the bar never shows an entry whose callback
        has gone.
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

        The comparison and the removal are one critical section, so no registration
        can land between them and no successor's state can be taken. A session that
        lost the slot while suspended removes nothing and is told ``kept``; a
        session the lease sweep already took is told ``session_gone``, which is not
        the same answer, because in that case nobody holds the connection and the
        entries the bar is still showing have no owner left.
        """
        with self._lock:
            session = self._sessions.get(connection_id)
            if session is None:
                return "session_gone"
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

        The compare-and-set the two-lock design could not express. The caller reads
        the leg through :meth:`listener_of` to decide what to tell an unreachable
        connection, and hands that leg back here; between those two moments the leg
        may have torn down or been replaced, and committing anyway would leave an
        entry with no listener and nothing left that would ever withdraw it. Because
        the slot and the callbacks are one value under this lock, the comparison and
        the write are a single critical section rather than a re-read that races.

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

    def _renewed(self, connection_id: ConnectionId) -> ClientSession:
        """The connection's session, renewed now, or a fresh one; caller locks.

        Every contact starts here, so arriving is one concept with one
        implementation: an existing session keeps its connect time and pushes its
        lease forward, and a first contact stamps the monotonic connect time.
        """
        now = self._clock()
        existing = self._sessions.get(connection_id)
        return existing.renewed(now) if existing is not None else ClientSession(now)
