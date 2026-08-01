"""ServiceRunner — a service's blocking work, run where it cannot cost the leg.

Everything a service does blocks: servicing a Beads click shells out to ``bd``
and pushes a scene over HTTP, and the warm-up behind the entry is the same query
without the push. None of it may run on the leg's loop, which is the one renewing
the session's lease — a slow click running there would lapse the very session
whose menu item was clicked, so the entry would vanish mid-service and the push
would land from a session the Hub had already swept.

Nor may any of it reach the receive loop as an exception. An escaping error ends
``listen`` and tears down a socket that is perfectly healthy, so a single bad
click would cost the session its leg and its menu entry. Both jobs here therefore
end in a log line rather than a raise.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Self, final

from punt_lux.rest_client import LuxRestClient
from punt_lux.rest_transport import HubUnavailableError

if TYPE_CHECKING:
    from punt_lux.applets.latency import ClickLatency
    from punt_lux.applets.service import AppletService
    from punt_lux.domain.hub.client_identity import ClientIdentity

logger = logging.getLogger(__name__)

__all__ = ["ServiceRunner"]


@final
class ServiceRunner:
    """The service's work, off the loop and inside a boundary it cannot escape."""

    _identity: ClientIdentity
    _service: AppletService
    __slots__ = ("_identity", "_service")

    def __new__(cls, identity: ClientIdentity, service: AppletService) -> Self:
        self = super().__new__(cls)
        self._identity = identity
        self._service = service
        return self

    async def clicked(self, latency: ClickLatency) -> None:
        """Service one click on a worker thread, leaving the loop free to renew.

        The click has already started: its clock was begun where it arrived, so
        the hop to the thread is inside the number rather than hidden beside it.
        Only the waiting happens here.
        """
        await asyncio.to_thread(self._serviced, latency)

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
        """Answer the click, then do its work, absorbing failure either way.

        The order is the point. The visible answer goes first and is measured
        against its budget; only then does the slow half run, however long it
        takes. Running them the other way round is what put a database query
        between a user's click and any sign it had registered.

        A Hub that cannot be reached is the ordinary failure: a restart between
        the click and the push. It is reported at WARNING because a click that
        produced nothing is something the user is waiting on, and this process
        logs at WARNING and above. The transport's own sentence goes with it,
        because a push that timed out and a luxd that is not running are
        different problems and only that sentence tells them apart.

        The line saying where the click's time went is reported last and
        unconditionally, so a click that failed still says which stage it failed
        in and how long it had been running by then.
        """
        try:
            client = self._rest()
            with latency.answering():
                self._service.acknowledge(client, latency)
            self._service.service(client, latency)
        except HubUnavailableError as exc:
            logger.warning("this click rendered nothing — luxd unreachable: %s", exc)
        except Exception:
            logger.exception("servicing a click failed; the leg stays up")
        finally:
            latency.report()

    def _rest(self) -> LuxRestClient:
        """Build a REST client for the current luxd, under the session's identity.

        Built per use rather than held, because the port is luxd's current one: a
        Hub that restarted onto a new port is followed here exactly as the listen
        client follows it, instead of pushing to a port nobody is on.
        """
        return LuxRestClient.for_identity(self._identity)
