"""luxd's persistent WebSocket listen leg — the Hub's push side of the pickup matrix.

A daemon holds one WebSocket to luxd and receives, live, both the pub-sub events it
subscribed to and the menu-callback clicks routed to its session.
:class:`HubListenSession` is one such connection; :class:`HubListenTransport`
mounts the ``/ws`` route and builds a session per connection.

The session is the bridge between two worlds. Hub-side, ``publish`` and a menu
click run on arbitrary threads (an MCP tool thread, the click-dispatch thread);
the WebSocket lives on the server's event loop. So the pub-sub writer and the
:class:`~punt_lux.domain.hub.callback_hold.CallbackListener` wake both hop onto the
loop with ``call_soon_threadsafe`` and enqueue a frame the write task drains — no
Hub lock is ever taken from the loop except the router's own, and never nested with
the client-registry lock, so the leg keeps PR-1's lock discipline. Connection-bound
state (the writer, the listener, the subscriptions) is torn down on disconnect; the
session, its lease, and its callback hold persist so a reconnect within the lease
drains the buffered clicks.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING, Self, final

from pydantic import ValidationError
from starlette.websockets import WebSocket, WebSocketDisconnect

from punt_lux.connection_identity import connection_for
from punt_lux.domain.hub import hub, hub_display
from punt_lux.domain.hub.client_identity import ClientIdentity
from punt_lux.domain.hub.replicator_instance import (
    hub_callback_router,
    hub_replicator,
)
from punt_lux.domain.ids import Topic
from punt_lux.identity_headers import ClientHeaders
from punt_lux.protocol.messages.listen import (
    CallbackFrame,
    ClientFrames,
    EventFrame,
    ReadyFrame,
    RenewFrame,
    ServerFrame,
    SubscribeFrame,
)

if TYPE_CHECKING:
    from fastapi import FastAPI

    from punt_lux.domain.hub.callback_hold import CallbackRouter
    from punt_lux.domain.hub.hub import Hub
    from punt_lux.domain.hub.hub_clients import HubClientRegistry
    from punt_lux.domain.ids import ConnectionId
    from punt_lux.operations.ports import DirtyMarker
    from punt_lux.protocol.messages.observer import ObserverMessage

logger = logging.getLogger(__name__)

__all__ = ["HubListenSession", "HubListenTransport"]

WS_PATH = "/ws"

# A client that declares no identity in its handshake headers is refused: a listen
# leg owns a session, and only a named client may. 1008 is the WebSocket policy code.
_POLICY_VIOLATION = 1008
# A client that sends a frame the wire does not define is closed as a protocol
# violation (1002) rather than left to bubble into a 1011 server error.
_PROTOCOL_ERROR = 1002


@final
class HubListenSession:
    """One persistent connection: its identity, its outbound queue, and its bridges.

    Implements the :class:`~punt_lux.domain.hub.callback_hold.CallbackListener`
    ``wake`` so a routed click pushes at once, and exposes ``deliver_event`` as this
    connection's Hub pub-sub writer. Both hop onto the loop and enqueue a frame.
    """

    _ws: WebSocket
    _conn: ConnectionId
    _identity: ClientIdentity
    _hub: Hub
    _clients: HubClientRegistry
    _router: CallbackRouter
    _outbound: asyncio.Queue[ServerFrame]
    _loop: asyncio.AbstractEventLoop
    _menus: DirtyMarker
    __slots__ = (
        "_clients",
        "_conn",
        "_hub",
        "_identity",
        "_loop",
        "_menus",
        "_outbound",
        "_router",
        "_ws",
    )

    def __new__(
        cls,
        ws: WebSocket,
        conn: ConnectionId,
        identity: ClientIdentity,
        hub: Hub,
        clients: HubClientRegistry,
        router: CallbackRouter,
        menus: DirtyMarker,
    ) -> Self:
        self = super().__new__(cls)
        self._ws = ws
        self._conn = conn
        self._identity = identity
        self._hub = hub
        self._clients = clients
        self._router = router
        self._menus = menus
        self._outbound = asyncio.Queue()
        self._loop = asyncio.get_running_loop()
        return self

    async def run(self) -> None:
        """Accept the connection, wire its bridges, and pump until it disconnects.

        Everything from the first piece of registered state onward is inside the
        teardown's guard. A client that goes away between the accept and the
        handshake write is the case that needs it: the listener is registered by
        then, and if the failing write escaped un-torn-down the Hub would hold a
        listener for a connection nothing can reach — and would then admit a
        menu callback from that identity, because holding a listener is exactly
        what the registration gate checks for.
        """
        await self._ws.accept()
        self._loop = asyncio.get_running_loop()
        try:
            self._clients.record(self._conn, self._identity)
            self._hub.register_writer(self._conn, self.deliver_event)
            self._router.add_listener(self._conn, self)
            await self._ws.send_text(
                ReadyFrame(connection_id=str(self._conn)).model_dump_json()
            )
            self._drain_callbacks()  # push clicks buffered before this (re)connect
            await self._pump()
        finally:
            self._teardown()

    async def _pump(self) -> None:
        """Read until the peer goes away, with the writer draining alongside."""
        writer = asyncio.create_task(self._write_loop())
        try:
            await self._read_loop()
        finally:
            writer.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await writer

    def wake(self) -> None:
        """CallbackListener: a click was routed to this session — schedule a drain."""
        self._loop.call_soon_threadsafe(self._drain_callbacks)

    def deliver_event(self, message: ObserverMessage) -> None:
        """Hub pub-sub writer: enqueue a subscribed topic's event onto the loop.

        Runs on the publisher's thread, so it hops to the loop rather than touching
        the WebSocket or the asyncio queue directly.
        """
        frame = EventFrame(topic=message.topic, payload=dict(message.payload))
        self._loop.call_soon_threadsafe(self._outbound.put_nowait, frame)

    async def _read_loop(self) -> None:
        """Apply inbound frames until the client disconnects; any frame renews.

        A frame the wire does not define is a protocol violation, not a server
        fault: the connection is closed cleanly (1002) rather than letting the
        parse error bubble into a 1011 internal error, which would also mislog a
        misbehaving client as a server bug.
        """
        while True:
            try:
                raw = await self._ws.receive_text()
            except WebSocketDisconnect:
                return
            self._clients.record(self._conn, self._identity)
            try:
                frame = ClientFrames.validate_json(raw)
            except ValidationError:
                logger.info("listen client sent a malformed frame; closing")
                await self._ws.close(code=_PROTOCOL_ERROR)
                return
            self._apply(frame)

    def _apply(self, frame: SubscribeFrame | RenewFrame) -> None:
        """Act on one parsed client frame — subscribe, or a bare renewal."""
        match frame:
            case SubscribeFrame(topics=topics):
                for topic in topics:
                    self._hub.subscribe(self._conn, Topic(topic))
            case RenewFrame():
                pass  # the lease renewal already happened on receipt

    async def _write_loop(self) -> None:
        """Drain the outbound queue to the socket until the peer or a cancel ends it.

        A send to a peer that is already going away raises (a ``WebSocketDisconnect``
        or, once starlette has seen the close, a ``RuntimeError``); that is a normal
        end of the connection, not a server error, so it ends the loop cleanly rather
        than propagating out of ``run`` and turning a routine disconnect into a fault.
        """
        while True:
            frame = await self._outbound.get()
            try:
                await self._ws.send_text(frame.model_dump_json())
            except (WebSocketDisconnect, RuntimeError):
                return

    def _drain_callbacks(self) -> None:
        """Take this session's held invocations and enqueue one frame each.

        Runs on the loop thread (direct on connect, scheduled by ``wake`` after);
        ``take`` clears the hold, so each click is delivered once.
        """
        for invocation in self._router.take(self._conn):
            self._outbound.put_nowait(CallbackFrame(callback_id=invocation.callback_id))

    def _teardown(self) -> None:
        """Drop everything the socket carried, including the session's menu items.

        The writer, the subscriptions, and the listener cannot outlive the socket.
        Neither can the callbacks: a menu item is delivered by push, so one whose
        listener has gone is an entry the user can click into silence — the click
        routes, lands in a hold, and nothing ever drains it. They are withdrawn
        here, and the menu is re-pushed so the entry leaves the bar with the
        connection that owned it.

        The session, its identity, and its lease stay, and so does its hold: a
        reconnect within the lease drains the clicks buffered across the gap and
        re-registers its callbacks from ``on_connect``. So a transient drop heals
        itself, while a process that is gone stays gone.
        """
        self._router.remove_listener(self._conn)
        if self._clients.withdraw_callbacks(self._conn):
            self._menus.mark_menus()
        self._hub.on_disconnect(self._conn)


@final
class HubListenTransport:
    """Mounts ``/ws`` and builds a :class:`HubListenSession` per connection."""

    _hub: Hub
    _clients: HubClientRegistry
    _router: CallbackRouter
    _menus: DirtyMarker
    __slots__ = ("_clients", "_hub", "_menus", "_router")

    def __new__(
        cls,
        hub: Hub,
        clients: HubClientRegistry,
        router: CallbackRouter,
        menus: DirtyMarker,
    ) -> Self:
        self = super().__new__(cls)
        self._hub = hub
        self._clients = clients
        self._router = router
        self._menus = menus
        return self

    @classmethod
    def for_hub(cls) -> Self:
        """Wire the transport over the Hub's process singletons."""
        return cls(hub, hub_display.clients, hub_callback_router, hub_replicator)

    def mount(self, app: FastAPI) -> None:
        """Add the ``/ws`` WebSocket route to the parent app."""
        app.add_api_websocket_route(WS_PATH, self._endpoint, name="listen")

    async def _endpoint(self, websocket: WebSocket) -> None:
        """Resolve the client's identity from the handshake, then serve its session.

        The identity rides the ``X-Lux-Client-*`` handshake headers exactly as it
        does on REST, and the connection is derived from the same declaration dict
        (:func:`connection_for`), so the two legs resolve to one shared id. An
        unidentified or malformed handshake is refused with a policy-violation close
        rather than served an anonymous session.
        """
        declaration = ClientHeaders.declaration_from(websocket.headers)
        identity = self._identity_of(declaration)
        if declaration is None or identity is None:
            await websocket.close(code=_POLICY_VIOLATION)
            return
        conn = connection_for(declaration)
        session = HubListenSession(
            websocket,
            conn,
            identity,
            self._hub,
            self._clients,
            self._router,
            self._menus,
        )
        await session.run()

    @staticmethod
    def _identity_of(declaration: dict[str, object] | None) -> ClientIdentity | None:
        """Validate a handshake declaration into an identity, or ``None`` if unusable.

        A wire boundary: an unnamed handshake (``declaration`` is ``None``), or one
        whose identity fields are garbled, is refused the leg — the absence is the
        documented outcome, not a raised error that would crash the connection.
        """
        if declaration is None:
            return None
        try:
            return ClientIdentity.model_validate(declaration)
        except ValidationError:
            logger.info("listen handshake declared a malformed identity; refusing")
            return None
