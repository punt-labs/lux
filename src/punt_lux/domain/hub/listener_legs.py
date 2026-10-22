"""ListenerLegs — each connection's listen leg, written under the registry's lock.

A connection's leg and its menu callbacks live on its session, and one connection is
shared by successive sessions of one identity, so every write is a compare against
the session occupying the slot: :meth:`attach`, :meth:`register_callback`, and
:meth:`detach` each make that compare-and-write one critical section. The sessions
and the lock are the registry's own, shared by reference, so these writes and the
registry's are serialized together.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.hub.session_write import SessionWrite

if TYPE_CHECKING:
    from collections.abc import Callable

    from punt_lux.domain.hub.callback_ports import CallbackListener
    from punt_lux.domain.hub.client_identity import ClientIdentity
    from punt_lux.domain.hub.client_session import ClientSession
    from punt_lux.domain.hub.registry_outcomes import (
        CallbackRegistration,
        ListenerDetachment,
    )
    from punt_lux.domain.hub.session_callback import SessionCallback
    from punt_lux.domain.hub.session_write import Attachment
    from punt_lux.domain.ids import ConnectionId

__all__ = ["ListenerLegs"]


@final
class ListenerLegs:
    """Take, release, and read the listener slot of the registry's sessions."""

    _sessions: dict[ConnectionId, ClientSession]
    _lock: threading.Lock
    _clock: Callable[[], float]
    __slots__ = ("_clock", "_lock", "_sessions")

    def __new__(
        cls,
        sessions: dict[ConnectionId, ClientSession],
        lock: threading.Lock,
        clock: Callable[[], float],
    ) -> Self:
        self = super().__new__(cls)
        self._sessions = sessions
        self._lock = lock
        self._clock = clock
        return self

    def attach(
        self,
        connection_id: ConnectionId,
        identity: ClientIdentity,
        listener: CallbackListener,
    ) -> Attachment:
        """Install ``listener`` as the connection's leg, recording ``identity``.

        Records and takes the slot in one step; taking it clears the previous
        occupant's callbacks and reports ``attached_over_callbacks``, alongside how
        the write changed who the Clients menu lists.
        """
        with self._lock:
            write = SessionWrite.attached(
                self._sessions.get(connection_id), self._clock(), identity, listener
            )
            self._sessions[connection_id] = write.after
            return write.attachment

    def detach(
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

    def listener_for(self, connection_id: ConnectionId) -> CallbackListener | None:
        """The connection's listen leg, or ``None`` when it holds none."""
        with self._lock:
            session = self._sessions.get(connection_id)
            return session.listener if session is not None else None
