"""LeaseReapSweep — the Hub event-loop task that reaps lapsed client leases.

The lease is a real backstop, not just a bookkeeping field: a connection whose
transport died and whose lease has lapsed must eventually depart on its own,
with no read, no other connection's write, and no detected disconnect required.
This task is what supplies that "on its own" — the identical periodic-task shape
``ExpirySweep`` already runs on this same Hub event loop for frame-TTL expiry,
so a lapsed lease gets a matching backstop rather than a second timer thread.

``sweep()`` is the deterministic entry point: call it directly with an injected
clock to prove reap-and-release fires with no other activity in the picture.
``run()`` is what actually drives it in production, on luxd's event loop.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Protocol, Self, final, runtime_checkable

if TYPE_CHECKING:
    from punt_lux.domain.ids import ConnectionId

__all__ = ["LeaseReapSweep", "LeaseReaper"]

logger = logging.getLogger(__name__)

# Comfortably under every kind's default TTL (SessionLease._TTL_BY_KIND's
# shortest, "cli", is 90s) and under the bead's own declared-TTL example
# (30s) -- close enough that a lapsed lease discharges promptly without
# polling the registry needlessly often.
_POLL_SECONDS = 15.0


@runtime_checkable
class LeaseReaper(Protocol):
    """The one question the sweep asks — satisfied by ``HubDisplay``."""

    def reap_lapsed_leases(self) -> frozenset[ConnectionId]:
        """Depart every lapsed connection now; return the ids that left."""
        ...


@final
class LeaseReapSweep:
    """Drive the lease's background reap on the Hub event loop: sweep, wait, repeat."""

    _reaper: LeaseReaper
    _interval: float
    __slots__ = ("_interval", "_reaper")

    def __new__(
        cls, reaper: LeaseReaper, interval_seconds: float = _POLL_SECONDS
    ) -> Self:
        self = super().__new__(cls)
        self._reaper = reaper
        self._interval = interval_seconds
        return self

    def sweep(self) -> frozenset[ConnectionId]:
        """Run one reap pass; return the ids departed. The deterministic test hook."""
        return self._reaper.reap_lapsed_leases()

    async def run(self) -> None:
        """Sweep-wait-repeat until the task is cancelled at shutdown.

        The sweep is guarded (PY-EH-6): a raise from it is logged and the loop
        backs off the poll interval rather than terminating or spinning.
        ``CancelledError`` is not caught, so shutdown cancellation ends it.
        """
        while True:
            try:
                self.sweep()
                await asyncio.sleep(self._interval)
            except Exception:
                logger.exception("lease-reap cycle failed; backing off the poll")
                await asyncio.sleep(self._interval)
