"""ReconnectSignal -- the wait that paces a replicator while no display is connected.

DES-093: pacing, backoff and the manifest reconcile belong to the registry's side of the
connection, never to the display's process. A replicator that finds no display waits
here for the next reconnect instead of spinning, and a stop wakes it so the join is
never trapped behind the wait. A reconnect is a generation: a waiter snapshots the
generation before it dials and waits for one past it, so a reconnect that lands between
its dial and its wait is seen, never lost. The signal has one lock of its own, a leaf:
the registry notes a reconnect while it holds its own lock, and a waiter holds only
this one.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from punt_lux.domain.hub.reconnect_wait import ReconnectWait

__all__ = ["ReconnectSignal"]


@final
class ReconnectSignal:
    """Counts reconnects, parks waiters for the next one, and wakes them on a stop."""

    _cond: threading.Condition
    _generation: int
    _stop_requested: bool
    __slots__ = ("_cond", "_generation", "_stop_requested")

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._cond = threading.Condition()
        self._generation = 0
        self._stop_requested = False
        return self

    @property
    def reconnect_generation(self) -> int:
        """Snapshot BEFORE a dial attempt, so a racing reconnect is caught."""
        with self._cond:
            return self._generation

    def reconnected(self) -> None:
        """Note a not-connected to connected edge and wake every waiter."""
        with self._cond:
            self._generation += 1
            self._cond.notify_all()

    def wait_for_reconnect(self, wait: ReconnectWait) -> bool:
        """Block for a reconnect past ``wait.since_gen`` or a stop; race-free."""
        with self._cond:
            return self._cond.wait_for(
                lambda: self._generation > wait.since_gen or self._stop_requested,
                wait.timeout,
            )

    def request_stop(self) -> None:
        """Wake every parked waiter; latches permanently."""
        with self._cond:
            self._stop_requested = True
            self._cond.notify_all()
