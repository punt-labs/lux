"""ServiceRunner — a service's blocking work, run where it cannot cost the leg.

Everything a service does blocks: servicing a Beads click shells out to ``bd``
and pushes a scene over HTTP, and the warm-up behind the entry is the same query
without the push. None of it may run on the leg's loop, which is the one renewing
the session's lease — a slow click running there would lapse the very session
whose menu item was clicked, so the entry would vanish mid-service and the push
would land from a session the Hub had already swept.

Nor may any of it reach the receive loop as an exception. An escaping error ends
``listen`` and tears down a socket that is perfectly healthy, so a single bad
click would cost the session its leg and its menu entry. Nothing awaits these
jobs either — the leg starts them and reads its next frame — so a failure that
got past them would end in a task nobody reads. Both therefore end in a log line
rather than a raise.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Self, final

from punt_lux.applets.board_ops import ScopedBoardOps
from punt_lux.applets.serviced_click import ServicedClick
from punt_lux.applets.single_flight import SingleFlight
from punt_lux.client.facade import LuxClient

if TYPE_CHECKING:
    from punt_lux.applets.board_ops import BoardOps
    from punt_lux.applets.latency import ClickLatency
    from punt_lux.applets.service import AppletService
    from punt_lux.domain.hub.client_identity import ClientIdentity

logger = logging.getLogger(__name__)

__all__ = ["ServiceRunner"]


@final
class ServiceRunner:
    """The service's work, off the loop and inside a boundary it cannot escape."""

    _identity: ClientIdentity
    _running: SingleFlight
    _service: AppletService
    __slots__ = ("_identity", "_running", "_service")

    def __new__(cls, identity: ClientIdentity, service: AppletService) -> Self:
        self = super().__new__(cls)
        self._identity = identity
        self._service = service
        # One query at a time, across every click this session's entry gets.
        self._running = SingleFlight()
        return self

    async def clicked(self, latency: ClickLatency) -> None:
        """Service one click on a worker thread, leaving the loop free to renew.

        The click has already started: its clock was begun where it arrived, so
        the hop to the thread is inside the number rather than hidden beside it.
        Only the waiting happens here — and a hop that could not be made is
        caught, because nobody is waiting on this coroutine to hear about it.
        """
        try:
            await asyncio.to_thread(self._serviced, latency)
        except Exception:
            logger.exception("a click could not be serviced at all; the leg stays up")

    async def warmed(self) -> None:
        """Run the service's warm-up on a worker thread, absorbing its failures.

        Blocking like everything else a service does, and equally not worth the
        leg: the only cost of a warm-up that failed is a first click that waits,
        so it is reported here rather than left to a task nobody awaits.
        """
        try:
            await asyncio.to_thread(self._service.prefetch)
        except Exception:
            logger.exception("the applet's prefetch failed; the first click waits")

    def _serviced(self, latency: ClickLatency) -> None:
        """Run one click's servicing, on the worker thread this was handed to."""
        ServicedClick(self._service, self._running, self._rest, latency).served()

    def _rest(self) -> BoardOps:
        """Build a Hub connection, under the session's identity; built per use."""
        return ScopedBoardOps.for_client(LuxClient.for_identity(self._identity))
