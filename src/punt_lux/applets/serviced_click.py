"""ServicedClick — one click: the answer the user sees, and the work behind it.

The order is the point. The visible answer goes first and is measured against
its budget; only then does the slow half run, however long it takes. Running
them the other way round is what put a database query between a user's click and
any sign it had registered.

The work behind two clicks is one piece of work. A click arriving while a query
is running is answered from what the applet holds and stands down: the query
already in flight reads the same issues, and the board it produces lands in the
frame this click has just raised, so it serves both. Starting a second would
fetch rows the first is already fetching, and a user drumming on the entry would
start one per click.

A click is handed the way to reach luxd rather than a client, because building
one reads luxd's current port and a Hub that has just restarted makes that read
fail. Built here, that failure is one more thing the click can tell the user
about; built outside, it would be a click that did nothing and said nothing.

Nothing leaves here as an exception. This runs on a worker thread nobody waits
on, so a failure escaping it would end in a task nobody reads — while the user,
who is waiting on a click, was told nothing at all.
"""

from __future__ import annotations

import logging
from functools import partial
from typing import TYPE_CHECKING, Self, final

from punt_lux.rest_transport import HubUnavailableError

if TYPE_CHECKING:
    from collections.abc import Callable

    from punt_lux.applets.board_ops import BoardOps
    from punt_lux.applets.latency import ClickLatency
    from punt_lux.applets.service import AppletService
    from punt_lux.applets.single_flight import SingleFlight

logger = logging.getLogger(__name__)

__all__ = ["ServicedClick"]

# What a click that found a query already running says on its line: the stage it
# did not spend, and why there is no figure for it.
_STOOD_DOWN = "stood down"
_ALREADY_RUNNING = "a load was already running"


@final
class ServicedClick:
    """One click of a session's menu entry, from its answer to the line it leaves."""

    _connect: Callable[[], BoardOps]
    _latency: ClickLatency
    _running: SingleFlight
    _service: AppletService
    __slots__ = ("_connect", "_latency", "_running", "_service")

    def __new__(
        cls,
        service: AppletService,
        running: SingleFlight,
        connect: Callable[[], BoardOps],
        latency: ClickLatency,
    ) -> Self:
        self = super().__new__(cls)
        self._service = service
        self._running = running
        self._connect = connect
        self._latency = latency
        return self

    def served(self) -> None:
        """Answer the click, then do its work, absorbing failure either way.

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
            client = self._connect()
            self._answered(client)
            self._worked(client)
        except HubUnavailableError as exc:
            logger.warning("this click rendered nothing — luxd unreachable: %s", exc)
        except Exception:
            logger.exception("servicing a click failed; the leg stays up")
        finally:
            self._latency.report()

    def _answered(self, client: BoardOps) -> None:
        """Put something on screen — the one stage held to the click's budget."""
        with self._latency.answering():
            self._service.acknowledge(client, self._latency)

    def _worked(self, client: BoardOps) -> None:
        """Do the click's work, unless the click before it is still doing it.

        The user is not made to wait for their answer either way: that has
        already happened, above. A click that stood down says so on its own line
        rather than reporting figures for a query it never ran.
        """
        if self._running.ran(partial(self._service.service, client, self._latency)):
            return
        with self._latency.stage(_STOOD_DOWN):
            self._latency.note(_ALREADY_RUNNING)
