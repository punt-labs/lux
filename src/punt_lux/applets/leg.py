"""AppletLeg — the connection an applet holds, and what it does with a click.

A menu entry must launch in the time a user reads as instant, which rules out
both a poll and a chat turn: nothing that waits for a model to be asked can meet
it. So an applet holds a live connection to luxd, registers its callbacks on it,
and does the work itself the moment a click arrives.

The leg owns the applet's event loop and nothing that blocks may run on it — not
the work a click asks for, and not the load that runs ahead of the first click.
What must keep running there is the keepalive that holds the session's lease.
Servicing a Beads click shells out to ``bd`` and pushes a scene over HTTP —
both blocking, and ``bd`` may take as long as its own timeout. A slow click
running *on* the loop would starve the renewal and lapse the very session whose
menu item was clicked, so the entry would vanish mid-service and the push would
land from a session the Hub had already swept. Blocking work therefore goes to a
worker thread, and the loop stays free to keep the lease alive while it runs.

Nor does the leg *wait* for that thread: its receive loop reads the next frame
only when the handler for this one returns, so a click awaited here would hold
the click behind it — a user clicking again — for the length of a query. Work is
started and returned from, in :class:`~punt_lux.applets.underway.Underway`.

The leg has no stop of its own: it runs until whoever started it cancels it,
which is the applet, when its session goes. The socket drops with the process and
the Hub sweeps the menu entry with the lease, so there is no shutdown to get
wrong even if the exit is not clean.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Self, final

from punt_lux.applets.latency import ClickLatency
from punt_lux.applets.runner import ServiceRunner
from punt_lux.applets.underway import Underway
from punt_lux.client.facade import LuxClient
from punt_lux.hub_client import LuxHubClient
from punt_lux.operations import Ok, OpError
from punt_lux.rest_transport import HubUnavailableError

if TYPE_CHECKING:
    from collections.abc import Mapping

    from punt_lux.applets.service import AppletService
    from punt_lux.client._sync_ops import CallbackConvenienceOps
    from punt_lux.domain.hub.client_identity import ClientIdentity

logger = logging.getLogger(__name__)

__all__ = ["AppletLeg"]

# How long to wait before reaching for luxd again when it is down or restarting.
# The leg's own reconnect handles a live Hub going away; this covers the case
# where there is nothing to connect to yet, so it need only be prompt in human
# terms, not tight.
_HUB_RETRY_SECONDS = 2.0


@final
class AppletLeg:
    """A session's live connection to luxd: register on connect, service on click."""

    _identity: ClientIdentity
    _runner: ServiceRunner
    _service: AppletService
    _underway: Underway
    __slots__ = ("_identity", "_runner", "_service", "_underway")

    def __new__(cls, identity: ClientIdentity, service: AppletService) -> Self:
        self = super().__new__(cls)
        self._identity = identity
        self._service = service
        self._runner = ServiceRunner(identity, service)
        self._underway = Underway()
        return self

    async def serve(self) -> None:
        """Hold the leg until cancelled, reaching for luxd again when it drops.

        ``listen`` reconnects on its own while luxd is merely unreachable, so this
        loop covers only the two cases it cannot: luxd not yet running when the
        session started, and the leg ending for a reason the client itself treats
        as fatal. Both wait a beat before trying again, so no failure can spin.
        """
        while True:
            await self._listen_once()
            await asyncio.sleep(_HUB_RETRY_SECONDS)

    async def _listen_once(self) -> None:
        """Build the leg and run it until it ends; report why rather than dying.

        This is a service boundary: an unexpected failure must not take the
        session's menu entry away for the rest of the session, so it is logged and
        the caller tries again.
        """
        try:
            await self._client().listen()
        except HubUnavailableError:
            logger.debug("luxd is not running yet; the applet will retry")
        except Exception:
            logger.exception("the applet's listen leg failed; retrying")

    def _client(self) -> LuxHubClient:
        """Build the listen client, registering the session's callbacks on connect."""
        return LuxHubClient.connect(
            self._identity,
            on_callback=self._on_callback,
            on_event=self._on_event,
            on_connect=self._register,
        )

    async def _register(self) -> None:
        """Put this session's entry in the menu — run after every handshake.

        Registration belongs here rather than before the connection, and not only
        because it must be re-done after a reconnect: the Hub refuses a callback
        from a connection that holds no listen leg, and the handshake this hook
        fires after is exactly what gives this connection one.

        The call is HTTP and therefore blocking, so it runs off the loop — the
        keepalive that holds this session's lease must not wait behind it.

        The entry is up the moment that call returns, and the warm-up behind it
        starts there: an entry nobody can click yet has nothing to prefetch for,
        and one that was refused never will.
        """
        result = await asyncio.to_thread(self._register_now)
        if isinstance(result, OpError):
            logger.error("this session's menu entry was refused: %s", result.reason)
            return
        self._start_prefetch()

    def _register_now(self) -> Ok | OpError:
        """Register the session's callback over REST — the blocking half."""
        return self._rest().register_callback(
            self._service.callback_id, self._service.label, self._service.frame_id
        )

    def _start_prefetch(self) -> None:
        """Warm the service up behind the handshake, never inside it.

        This runs from ``on_connect``, which the client awaits before it starts
        its receive loop and before the keepalive that holds this session's lease
        — so a prefetch awaited here would hold both for as long as ``bd`` takes.
        It is started, and the handshake goes on without it.
        """
        self._underway.start(self._runner.warmed())

    async def _on_callback(self, callback_id: str) -> None:
        """Route a click the Hub pushed, with no poll and no turn in between.

        The clock starts here, where the click arrives, because the contract it
        measures is the user's: from their click to something visible. The click
        is started rather than awaited, so the frame behind it — the next click —
        is read while this one is served, off the loop that renews the lease.
        """
        if callback_id != self._service.callback_id:
            logger.warning("no service for callback %r in this session", callback_id)
            return
        self._underway.start(self._runner.clicked(ClickLatency(callback_id)))

    @staticmethod
    def _on_event(topic: str, payload: Mapping[str, object]) -> None:
        """Ignore pub-sub traffic: this leg subscribes to no topics.

        The handler is required by the listen client, and a leg that subscribes to
        nothing should still say what arrived if anything ever does.
        """
        logger.debug("unsubscribed event on the session leg: %s %s", topic, payload)

    def _rest(self) -> CallbackConvenienceOps:
        """Build a Hub connection, sharing this leg's identity; built per use."""
        return LuxClient.for_identity(self._identity).sync
