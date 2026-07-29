"""The persistent hub client — connect-and-listen over luxd's WebSocket leg.

:class:`LuxHubClient` is the library surface a daemon uses to hold one live
connection to luxd: it subscribes to pub-sub topics and receives, in a blocking
receive loop, both those topics' events and the menu-callback clicks routed to its
session, dispatching each to an app handler. It carries the same
:class:`~punt_lux.domain.hub.client_identity.ClientIdentity` a
:class:`~punt_lux.rest_client.LuxRestClient` uses, so the daemon's scene pushes
(over REST) and its listen stream (over this WebSocket) resolve to one connection —
a callback the daemon registers over REST is delivered here.

The receive loop renews the lease on every contact and reconnects on a dropped
connection, re-declaring identity and re-subscribing, so a transient network gap is
invisible to the app: the Hub buffers the clicks it missed and drains them on
reconnect.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING, Self, final

import websockets

from punt_lux.hub_paths import HubPaths
from punt_lux.identity_headers import ClientHeaders
from punt_lux.protocol.messages.listen import (
    CallbackFrame,
    EventFrame,
    ReadyFrame,
    RenewFrame,
    ServerFrames,
    SubscribeFrame,
)
from punt_lux.rest_transport import HubUnavailableError

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping

    from websockets.asyncio.client import ClientConnection

    from punt_lux.domain.hub.client_identity import ClientIdentity

logger = logging.getLogger(__name__)

__all__ = ["CallbackHandler", "EventHandler", "LuxHubClient"]

# An app handler for a menu click (the callback id) and for a subscribed event
# (its topic and payload). Either may be sync or async; the loop awaits a coroutine.
type CallbackHandler = Callable[[str], Awaitable[None] | None]
type EventHandler = Callable[[str, Mapping[str, object]], Awaitable[None] | None]

# Reconnect backoff: start fast, double to a ceiling, reset on a clean session, so a
# briefly-down Hub is rejoined at once and a long-down one is retried at a sane rate.
_BASE_BACKOFF_SECONDS = 0.1
_MAX_BACKOFF_SECONDS = 5.0
# Send a keepalive this often; any frame renews the lease, so a quiet client stays live.
_RENEW_INTERVAL_SECONDS = 15.0


@final
class LuxHubClient:
    """A daemon's live connection to luxd: subscribe, receive, dispatch, reconnect."""

    _url: str
    _headers: dict[str, str]
    _on_callback: CallbackHandler
    _on_event: EventHandler
    _renew_interval: float
    _topics: set[str]
    _stopped: asyncio.Event
    _connection_id: str
    __slots__ = (
        "_connection_id",
        "_headers",
        "_on_callback",
        "_on_event",
        "_renew_interval",
        "_stopped",
        "_topics",
        "_url",
    )

    def __new__(
        cls,
        url: str,
        identity: ClientIdentity,
        *,
        on_callback: CallbackHandler,
        on_event: EventHandler,
        renew_interval: float = _RENEW_INTERVAL_SECONDS,
    ) -> Self:
        self = super().__new__(cls)
        self._url = url
        self._headers = ClientHeaders.to_wire(identity)
        self._on_callback = on_callback
        self._on_event = on_event
        self._renew_interval = renew_interval
        self._topics = set()
        self._stopped = asyncio.Event()
        self._connection_id = ""
        return self

    @classmethod
    def connect(
        cls,
        identity: ClientIdentity,
        *,
        on_callback: CallbackHandler,
        on_event: EventHandler,
        renew_interval: float = _RENEW_INTERVAL_SECONDS,
    ) -> Self:
        """Build a client for ``identity``, resolving luxd's port, or raise if down."""
        port = HubPaths().read_port()
        if port is None:
            raise HubUnavailableError(
                "luxd is not running. Run 'lux hub-install' to register the service."
            )
        return cls(
            f"ws://127.0.0.1:{port}/ws",
            identity,
            on_callback=on_callback,
            on_event=on_event,
            renew_interval=renew_interval,
        )

    @property
    def connection_id(self) -> str:
        """The connection id the Hub bound this client to, set at each handshake."""
        return self._connection_id

    def subscribe(self, *topics: str) -> None:
        """Record topics to subscribe on every (re)connect; safe before ``listen``."""
        self._topics.update(topics)

    def stop(self) -> None:
        """Ask the receive loop to finish after its current connection closes."""
        self._stopped.set()

    async def listen(self) -> None:
        """Hold a connection open, dispatching frames, until ``stop`` — reconnecting.

        Each dropped connection backs off and rejoins, re-declaring identity in the
        handshake headers and re-subscribing, so the app sees one continuous stream.
        """
        backoff = _BASE_BACKOFF_SECONDS
        while not self._stopped.is_set():
            try:
                async with websockets.connect(
                    self._url, additional_headers=self._headers
                ) as connection:
                    backoff = _BASE_BACKOFF_SECONDS
                    await self._run_session(connection)
            except (OSError, websockets.WebSocketException):
                if self._stopped.is_set():
                    return
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, _MAX_BACKOFF_SECONDS)

    async def _run_session(self, connection: ClientConnection) -> None:
        """Read the handshake, subscribe, then dispatch frames until the socket ends."""
        self._connection_id = self._ready(await connection.recv())
        if self._topics:
            await connection.send(
                SubscribeFrame(topics=tuple(sorted(self._topics))).model_dump_json()
            )
        renew = asyncio.create_task(self._renew_loop(connection))
        try:
            async for raw in connection:
                await self._dispatch(raw)
        finally:
            renew.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await renew

    @staticmethod
    def _ready(raw: str | bytes) -> str:
        """Read the handshake frame and return the bound connection id, or raise.

        The first frame is the Hub's :class:`ReadyFrame`; anything else means the
        server did not open the session as promised, which is a protocol fault, not
        a value to paper over.
        """
        frame = ServerFrames.validate_json(raw)
        if not isinstance(frame, ReadyFrame):
            msg = f"expected a ready handshake, got {frame.kind!r}"
            raise ValueError(msg)
        return frame.connection_id

    async def _dispatch(self, raw: str | bytes) -> None:
        """Route one server frame to its app handler; a stray ready frame is ignored."""
        frame = ServerFrames.validate_json(raw)
        match frame:
            case CallbackFrame(callback_id=callback_id):
                await self._await_maybe(self._on_callback(callback_id))
            case EventFrame(topic=topic, payload=payload):
                await self._await_maybe(self._on_event(topic, payload))
            case ReadyFrame():
                pass  # only valid at handshake; a mid-stream ready is inert

    async def _renew_loop(self, connection: ClientConnection) -> None:
        """Send a keepalive each interval so a quiet app's lease never lapses."""
        while True:
            await asyncio.sleep(self._renew_interval)
            await connection.send(RenewFrame().model_dump_json())

    @staticmethod
    async def _await_maybe(result: Awaitable[None] | None) -> None:
        """Await ``result`` when the handler was async; a sync handler returns None."""
        if result is not None:
            await result
