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

A routed invocation is pushed at once rather than waited for, by waking the
session's :class:`~punt_lux.domain.hub.callback_ports.CallbackListener`. The
listener belongs to the session, not to this router: it and the callbacks
registered against it are one slot in the client registry, under that registry's
lock, so installing, committing, and releasing are each one critical section. The
router reads the listener off the same live-session snapshot it routes against and
calls ``wake`` *after* releasing its own lock, like the replicator's menu flag, so
the notify never runs under a lock and no cross-lock path appears.

Push is the only delivery: a menu item must launch in the time a user reads as
instant, and a poll cannot promise that at any interval a client would run. So a
held listen leg is the *precondition* for owning a callback at all, and the hold
is not an alternative pickup route — it is the buffer that carries clicks across a
listener's transient gap until it reconnects and drains them.
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from contextlib import contextmanager
from typing import TYPE_CHECKING, Literal, Self, final

if TYPE_CHECKING:
    from collections.abc import Generator, Mapping

    from punt_lux.domain.hub.callback_ports import CallbackListener, LiveSessions
    from punt_lux.domain.hub.client_session import ClientSession
    from punt_lux.domain.hub.session_callback import CallbackInvocation
    from punt_lux.domain.ids import ConnectionId

logger = logging.getLogger(__name__)

__all__ = ["CallbackRouter", "CallbackRouting"]

# A routed invocation waits in its session's hold; a click for a lapsed session is
# ``provider_gone`` (the design's "provider is gone" notice), and one naming a
# callback the live session never registered is ``unknown_callback``.
CallbackRouting = Literal["routed", "provider_gone", "unknown_callback"]

# The most invocations one session's hold keeps before the oldest is dropped: a
# backstop against an undrained hold growing without bound, not a delivery quota.
_HOLD_CAPACITY = 32


@final
class _CallbackHold:
    """One session's bounded queue of pending invocations, oldest dropped when full.

    Not independently locked: the owning :class:`CallbackRouter` serializes every
    access under its one lock, so the hold is a plain bounded container.
    """

    _connection_id: ConnectionId
    _capacity: int
    _pending: deque[CallbackInvocation]
    __slots__ = ("_capacity", "_connection_id", "_pending")

    def __new__(cls, connection_id: ConnectionId, capacity: int) -> Self:
        self = super().__new__(cls)
        self._connection_id = connection_id
        self._capacity = capacity
        self._pending = deque(maxlen=capacity)
        return self

    def add(self, invocation: CallbackInvocation) -> None:
        """Append ``invocation``, saying so when a full hold drops the oldest.

        The deque's bound is what keeps an undrained hold from growing without
        end, but the click it discards was answered ``routed`` — the caller was
        told the work had been handed off, and it never ran. So the drop is
        reported for the same reason a departing hold reports what it loses: it
        is a click this module can lose with nobody noticing.
        """
        if len(self._pending) == self._capacity:
            logger.warning(
                "%s hold is full at %d; dropping routed invocation %s undelivered",
                self._connection_id,
                self._capacity,
                self._pending[0].callback_id,
            )
        self._pending.append(invocation)

    def take_all(self) -> tuple[CallbackInvocation, ...]:
        """Return every held invocation in arrival order and clear the hold."""
        drained = tuple(self._pending)
        self._pending.clear()
        return drained

    def snapshot(self) -> tuple[CallbackInvocation, ...]:
        """Return every held invocation in arrival order without clearing."""
        return tuple(self._pending)

    def report_dropped(self) -> None:
        """Say what goes with this hold when its session leaves; silent if empty.

        An empty hold going is routine bookkeeping. A hold with invocations still
        in it is not: every one of those clicks was answered ``routed``, so the
        caller was told the work had been handed off and it never ran. That is the
        one thing this module can lose without anyone noticing, so it says so.
        """
        if self._pending:
            logger.warning(
                "%s left with %d routed invocation(s) never delivered",
                self._connection_id,
                len(self._pending),
            )


@final
class CallbackRouter:
    """Route a click's invocation to the owning session's hold, or say why not."""

    _lookup: LiveSessions
    _holds: dict[ConnectionId, _CallbackHold]
    _lock: threading.Lock
    _capacity: int
    __slots__ = ("_capacity", "_holds", "_lock", "_lookup")

    def __new__(cls, lookup: LiveSessions, capacity: int = _HOLD_CAPACITY) -> Self:
        self = super().__new__(cls)
        self._lookup = lookup
        self._holds = {}
        self._lock = threading.Lock()
        self._capacity = capacity
        return self

    @contextmanager
    def _swept(self) -> Generator[Mapping[ConnectionId, ClientSession]]:
        """Hold the router lock over swept holds, yielding the live sessions.

        Every read and write of the holds enters here, so the lock discipline is
        structural rather than three methods each remembering it: the live read
        runs first and outside the router's lock — sweeping the client registry
        under *its* lock — and only then is this one taken, so the two never nest.
        Sweeping on the way in is what makes a departed session's hold
        unreachable rather than merely unwanted.
        """
        live = self._lookup.live_sessions()
        with self._lock:
            self._sweep(live)
            yield live

    def route(self, invocation: CallbackInvocation) -> CallbackRouting:
        """Hold ``invocation`` for its owning session, or report why it cannot land.

        A session gone from the live set is ``provider_gone``; a live session that
        never registered the callback is ``unknown_callback``. The listener comes
        off the same snapshot the routing decision was made against, and is woken
        *after* the lock is released, so no callout happens under the router lock.
        """
        with self._swept() as live:
            session = live.get(invocation.connection_id)
            if session is None:
                return "provider_gone"
            if not session.owns_callback(invocation.callback_id):
                return "unknown_callback"
            self._hold_for(invocation.connection_id).add(invocation)
            listener = session.listener
        if listener is not None:
            self._wake(listener)
        return "routed"

    @staticmethod
    def _wake(listener: CallbackListener) -> None:
        """Wake a listener, isolating a raising one from the routing.

        The hold write already committed before this runs, so a wake that raises —
        a listener whose loop or socket is mid-teardown — must not fail the route or
        lose the click; the invocation stays buffered for the next drain. The dead
        listener is left where it is: the slot belongs to the session that installed
        it, and only that session's teardown may release it. A router that cleared
        it here would be a second writer to state it does not own, which is the
        clobber this design exists to rule out.
        """
        try:
            listener.wake()
        except Exception:
            logger.exception("callback listener wake failed; the click stays held")

    def take(self, connection_id: ConnectionId) -> tuple[CallbackInvocation, ...]:
        """Take and clear the session's held invocations — the delivery legs' drain.

        A hold whose session has since left the live set is dropped by the entry
        sweep rather than delivered: the hold dies with the lease even when no
        ``route`` fired in between.
        """
        with self._swept():
            hold = self._holds.pop(connection_id, None)
            return hold.take_all() if hold is not None else ()

    def pending(self, connection_id: ConnectionId) -> tuple[CallbackInvocation, ...]:
        """Return the session's held invocations without clearing them.

        No production caller: this is what remains of the retired poll leg, kept
        because it is the only way to observe the hold without draining it, and
        the hold's own tests need to assert what is buffered and then that a
        later drain still returns it. Deliveries go through ``take``.
        """
        with self._swept():
            hold = self._holds.get(connection_id)
            return hold.snapshot() if hold is not None else ()

    def _sweep(self, live: Mapping[ConnectionId, ClientSession]) -> None:
        """Drop holds for sessions no longer live, each reporting what it loses.

        Caller holds the lock.
        """
        for connection_id in [c for c in self._holds if c not in live]:
            self._holds.pop(connection_id).report_dropped()

    def _hold_for(self, connection_id: ConnectionId) -> _CallbackHold:
        """Return the session's hold, creating it on first use; caller locks."""
        hold = self._holds.get(connection_id)
        if hold is None:
            hold = _CallbackHold(connection_id, self._capacity)
            self._holds[connection_id] = hold
        return hold
