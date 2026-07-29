"""The Hub-side hold for menu-callback invocations, and the router that fills it.

A click on a menu callback fires a :class:`CallbackInvocation` at the Hub, which
routes it to the session that owns the callback. The delivery legs that carry it
to the session (a live socket, an MCP stream, a periodic client's next beat) are a
later concern; this module lands the routing decision and a bounded per-session
hold those legs drain.

:class:`CallbackRouter` reads the live sessions to decide routing — a click for a
session whose lease has lapsed is answered ``provider_gone`` rather than held, and
a click naming a callback the live session never registered is ``unknown_callback``.
Holds for sessions that have left are swept as the router passes, so a departed
session never strands invocations. One lock serializes the holds; it never nests
with the client registry's lock (the live read completes before it is taken), so
the router adds no deadlock risk.

A persistent leg (a daemon holding a live connection) registers a
:class:`CallbackListener` for its connection so a routed invocation is pushed at
once rather than waited for. The listener is a payload-less wake, like the
replicator's menu flag: ``route`` snapshots it under the lock and calls ``wake``
*after* releasing the lock, so the notify never runs under the router lock and adds
no new lock or cross-lock path. A session with no registered listener — an MCP or
periodic client — falls through to the hold and drains it by polling, so the pickup
mode is chosen by listener presence, never by a client-kind branch.
"""

from __future__ import annotations

import threading
from collections import deque
from typing import TYPE_CHECKING, Literal, Protocol, Self, final, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Mapping

    from punt_lux.domain.hub.client_session import ClientSession
    from punt_lux.domain.hub.session_callback import CallbackInvocation
    from punt_lux.domain.ids import ConnectionId

__all__ = ["CallbackListener", "CallbackRouter", "CallbackRouting", "LiveSessions"]

# A routed invocation waits in its session's hold; a click for a lapsed session is
# ``provider_gone`` (the design's "provider is gone" notice), and one naming a
# callback the live session never registered is ``unknown_callback``.
CallbackRouting = Literal["routed", "provider_gone", "unknown_callback"]

# The most invocations one session's hold keeps before the oldest is dropped: a
# backstop against an undrained hold growing without bound, not a delivery quota.
_HOLD_CAPACITY = 32


@runtime_checkable
class LiveSessions(Protocol):
    """The live-session read the router routes against — the sessions still in lease."""

    def live_sessions(self) -> Mapping[ConnectionId, ClientSession]:
        """Return the sessions whose lease has not lapsed, sweeping the expired."""
        ...


@runtime_checkable
class CallbackListener(Protocol):
    """A persistent leg's wake: 'a routed invocation landed — drain and push it.'

    Payload-less by design, like the replicator's menu flag: the leg reads the hold
    itself on waking, so the wake carries no state the hold does not already own.
    """

    def wake(self) -> None:
        """Signal that a routed invocation is waiting for this connection."""
        ...


@final
class _CallbackHold:
    """One session's bounded queue of pending invocations, oldest dropped when full.

    Not independently locked: the owning :class:`CallbackRouter` serializes every
    access under its one lock, so the hold is a plain bounded container.
    """

    _pending: deque[CallbackInvocation]
    __slots__ = ("_pending",)

    def __new__(cls, capacity: int) -> Self:
        self = super().__new__(cls)
        self._pending = deque(maxlen=capacity)
        return self

    def add(self, invocation: CallbackInvocation) -> None:
        """Append ``invocation``; the deque drops the oldest past its capacity."""
        self._pending.append(invocation)

    def take_all(self) -> tuple[CallbackInvocation, ...]:
        """Return every held invocation in arrival order and clear the hold."""
        drained = tuple(self._pending)
        self._pending.clear()
        return drained

    def snapshot(self) -> tuple[CallbackInvocation, ...]:
        """Return every held invocation in arrival order without clearing."""
        return tuple(self._pending)


@final
class CallbackRouter:
    """Route a click's invocation to the owning session's hold, or say why not."""

    _lookup: LiveSessions
    _holds: dict[ConnectionId, _CallbackHold]
    _listeners: dict[ConnectionId, CallbackListener]
    _lock: threading.Lock
    _capacity: int
    __slots__ = ("_capacity", "_holds", "_listeners", "_lock", "_lookup")

    def __new__(cls, lookup: LiveSessions, capacity: int = _HOLD_CAPACITY) -> Self:
        self = super().__new__(cls)
        self._lookup = lookup
        self._holds = {}
        self._listeners = {}
        self._lock = threading.Lock()
        self._capacity = capacity
        return self

    def route(self, invocation: CallbackInvocation) -> CallbackRouting:
        """Hold ``invocation`` for its owning session, or report why it cannot land.

        The live read runs first and outside the router's lock, sweeping the client
        registry; only then is the hold lock taken, so the two locks never nest. A
        session gone from the live set is ``provider_gone``; a live session that
        never registered the callback is ``unknown_callback``. A routed invocation
        for a session with a registered persistent listener wakes it — the wake runs
        *after* the lock is released, so no callout happens under the router lock.
        """
        live = self._lookup.live_sessions()
        with self._lock:
            self._sweep(live)
            session = live.get(invocation.connection_id)
            if session is None:
                return "provider_gone"
            if not session.owns_callback(invocation.callback_id):
                return "unknown_callback"
            self._hold_for(invocation.connection_id).add(invocation)
            listener = self._listeners.get(invocation.connection_id)
        if listener is not None:
            listener.wake()
        return "routed"

    def add_listener(
        self, connection_id: ConnectionId, listener: CallbackListener
    ) -> None:
        """Register a persistent leg's wake for a connection, replacing any prior one.

        A live connection registers on connect so ``route`` pushes to it at once; it
        unregisters on disconnect. Listener lifetime is the connection's, not the
        lease's — a live connection renews its own lease — so the sweep leaves
        listeners alone and ``remove_listener`` is the only exit.
        """
        with self._lock:
            self._listeners[connection_id] = listener

    def remove_listener(self, connection_id: ConnectionId) -> None:
        """Drop a connection's registered listener. A no-op if none is registered."""
        with self._lock:
            self._listeners.pop(connection_id, None)

    def take(self, connection_id: ConnectionId) -> tuple[CallbackInvocation, ...]:
        """Take and clear the session's held invocations — the delivery legs' drain.

        Sweeps first, so a hold whose session has since left the live set is dropped
        rather than delivered: the hold dies with the lease even when no ``route``
        fired in between. The live read runs before the router lock, so the two
        locks never nest.
        """
        live = self._lookup.live_sessions()
        with self._lock:
            self._sweep(live)
            hold = self._holds.pop(connection_id, None)
            return hold.take_all() if hold is not None else ()

    def pending(self, connection_id: ConnectionId) -> tuple[CallbackInvocation, ...]:
        """Return the session's held invocations without clearing them.

        Sweeps first for the same reason as ``take``: an expired session's hold is
        never readable. The live read precedes the router lock, so no lock nests.
        """
        live = self._lookup.live_sessions()
        with self._lock:
            self._sweep(live)
            hold = self._holds.get(connection_id)
            return hold.snapshot() if hold is not None else ()

    def _sweep(self, live: Mapping[ConnectionId, ClientSession]) -> None:
        """Drop holds for sessions no longer live. Caller holds the lock."""
        for connection_id in [c for c in self._holds if c not in live]:
            del self._holds[connection_id]

    def _hold_for(self, connection_id: ConnectionId) -> _CallbackHold:
        """Return the session's hold, creating it on first use; caller locks."""
        hold = self._holds.get(connection_id)
        if hold is None:
            hold = _CallbackHold(self._capacity)
            self._holds[connection_id] = hold
        return hold
