"""The session's listen leg: hold luxd's WebSocket and service the clicks it pushes.

A menu entry must launch in the time a user reads as instant, which rules out
both a poll and a chat turn: nothing that waits for a model to be asked can meet
it. So the process serving a session's MCP surface also holds a live connection
to luxd on a thread of its own, registers the session's callbacks on it, and does
the work itself the moment a click arrives.

The thread is the whole concurrency story, deliberately. It owns its event loop,
its clients, and its handler; it shares no mutable state with the proxy that runs
on the main thread, so there is no lock here and none is needed. Servicing a click
runs to completion on that thread — the loop's only other job is a keepalive with
several beats of headroom — so a click is serviced start to finish without
interleaving with the next one.

It is a daemon thread and has no stop: the leg's life is the process's life. When
the session ends, stdin closes, the process exits, the socket drops, and the Hub
sweeps the session's menu entry with its lease. Nothing to shut down means no
shutdown to get wrong.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import TYPE_CHECKING, Protocol, Self, final, runtime_checkable

from punt_lux.hub_client import LuxHubClient
from punt_lux.operations import OpError
from punt_lux.rest_client import LuxRestClient
from punt_lux.rest_transport import HubUnavailableError

if TYPE_CHECKING:
    from collections.abc import Mapping

    from punt_lux.domain.hub.client_identity import ClientIdentity

logger = logging.getLogger(__name__)

__all__ = ["SessionCallbackLeg", "SessionService"]

# How long to wait before reaching for luxd again when it is down or restarting.
# The leg's own reconnect handles a live Hub going away; this covers the case
# where there is nothing to connect to yet, so it need only be prompt in human
# terms, not tight.
_HUB_RETRY_SECONDS = 2.0


@runtime_checkable
class SessionService(Protocol):
    """One callback a session owns: the entry it puts up and the work a click does."""

    @property
    def callback_id(self) -> str:
        """The id a click on this entry carries back to the session."""
        ...

    @property
    def label(self) -> str:
        """The entry the display shows under this session's submenu."""
        ...

    def service(self, client: LuxRestClient) -> None:
        """Do the work a click asks for, pushing whatever it produces via ``client``."""
        ...


@final
class SessionCallbackLeg:
    """A session's live connection to luxd: register on connect, service on click."""

    _identity: ClientIdentity
    _service: SessionService
    __slots__ = ("_identity", "_service")

    def __new__(cls, identity: ClientIdentity, service: SessionService) -> Self:
        self = super().__new__(cls)
        self._identity = identity
        self._service = service
        return self

    def start(self) -> None:
        """Run the leg on a daemon thread and return at once.

        Returning at once is the point: the caller is a session's MCP server, which
        must answer its first request in well under a second whether or not luxd is
        up yet. Nothing here blocks that — the connecting, the waiting, and the
        retrying all happen on the thread.
        """
        thread = threading.Thread(
            target=self._serve, name="lux-session-leg", daemon=True
        )
        thread.start()

    def _serve(self) -> None:
        """Hold the leg for the life of the process, reaching for luxd when it drops.

        ``listen`` reconnects on its own while luxd is merely unreachable, so this
        loop covers only the two cases it cannot: luxd not yet running when the
        session started, and the leg ending for a reason the client itself treats
        as fatal. Both wait a beat before trying again, so no failure can spin.
        """
        while True:
            self._listen_once()
            time.sleep(_HUB_RETRY_SECONDS)

    def _listen_once(self) -> None:
        """Build the leg and run it until it ends; report why rather than dying.

        The thread is a service boundary: an unexpected failure here must not take
        the session's menu entry away for the rest of the session, so it is logged
        and the caller tries again.
        """
        try:
            asyncio.run(self._client().listen())
        except HubUnavailableError:
            logger.debug("luxd is not running yet; the session leg will retry")
        except Exception:
            logger.exception("the session's listen leg failed; retrying")

    def _client(self) -> LuxHubClient:
        """Build the listen client, registering the session's callbacks on connect."""
        return LuxHubClient.connect(
            self._identity,
            on_callback=self._on_callback,
            on_event=self._on_event,
            on_connect=self._register,
        )

    def _register(self) -> None:
        """Put this session's entry in the menu — run after every handshake.

        Registration belongs here rather than before the connection, and not only
        because it must be re-done after a reconnect: the Hub refuses a callback
        from a connection that holds no listen leg, and the handshake this hook
        fires after is exactly what gives this connection one.
        """
        result = self._rest().register_callback(
            self._service.callback_id, self._service.label
        )
        if isinstance(result, OpError):
            logger.error("this session's menu entry was refused: %s", result.reason)

    def _on_callback(self, callback_id: str) -> None:
        """Service a click the Hub pushed, on this thread, with no turn in between."""
        if callback_id != self._service.callback_id:
            logger.warning("no service for callback %r in this session", callback_id)
            return
        self._service.service(self._rest())

    @staticmethod
    def _on_event(topic: str, payload: Mapping[str, object]) -> None:
        """Ignore pub-sub traffic: this leg subscribes to no topics.

        The handler is required by the listen client, and a leg that subscribes to
        nothing should still say what arrived if anything ever does.
        """
        logger.debug("unsubscribed event on the session leg: %s %s", topic, payload)

    def _rest(self) -> LuxRestClient:
        """Build a REST client for the current luxd, sharing this leg's identity.

        Built per use rather than held, because the port is luxd's current one: a
        Hub that restarted onto a new port is followed here exactly as the listen
        client follows it, instead of pushing to a port nobody is on.
        """
        return LuxRestClient.for_identity(self._identity)
