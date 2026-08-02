"""luxd's persistent WebSocket listen leg — the Hub's push side of the pickup matrix.

A daemon holds one WebSocket to luxd and receives, live, both the pub-sub events it
subscribed to and the menu-callback clicks routed to its session.
:class:`HubListenSession` is one such connection; the ``/ws`` route that builds
one per client lives in :mod:`punt_lux.ws_transport`.

The session is the bridge between two worlds. Hub-side, ``publish`` and a menu
click run on arbitrary threads (an MCP tool thread, the click-dispatch thread);
the WebSocket lives on the server's event loop. So the pub-sub writer and the
:class:`~punt_lux.domain.hub.callback_ports.CallbackListener` wake both hop onto
the loop with ``call_soon_threadsafe`` and enqueue a frame the write task drains.
The loop takes the client registry's lock to install and release the session's
listener slot, and the router's to drain the hold, but never one inside the other,
so no cross-lock path appears.

The connection is keyed by an identity-derived id, so successive sessions of one
identity share it, and the session occupying the listener slot is the connection's
ownership token: state installed here is released only by the session that
installed it, compared by object identity. Connection-bound state (the writer, the
listener, its callbacks, the subscriptions) goes on disconnect; the session, its
lease, and its callback hold persist so a reconnect within the lease drains the
buffered clicks.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING, Self, final

from pydantic import ValidationError
from starlette.websockets import WebSocket, WebSocketDisconnect

from punt_lux.domain.hub.client_identity import ClientIdentity
from punt_lux.domain.ids import Topic
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
    from punt_lux.domain.hub.callback_hold import CallbackRouter
    from punt_lux.domain.hub.hub import Hub
    from punt_lux.domain.hub.hub_clients import HubClientRegistry
    from punt_lux.domain.ids import ConnectionId
    from punt_lux.operations.ports import DirtyMarker
    from punt_lux.protocol.messages.observer import ObserverMessage

logger = logging.getLogger(__name__)

__all__ = ["HubListenSession"]

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

        The prologue runs as one uninterrupted stretch between the accept and the
        handshake write, so no other loop-side step can land inside it. Recording
        the identity and taking the connection's listener slot are one registry
        call for the same reason at thread scope: nothing may observe this session
        identified but unreachable, or holding the slot but anonymous.

        Taking the slot clears the entries its previous occupant owned, and the bar
        is re-pushed when it does. Nothing else would: this session may register
        nothing of its own, and a user clicking a cleared entry discovers the fault
        rather than repairing it.
        """
        await self._ws.accept()
        self._loop = asyncio.get_running_loop()
        try:
            attachment = self._clients.attach_listener(self._conn, self._identity, self)
            if attachment == "attached_over_callbacks":
                self._menus.mark_menus()
            self._hub.register_writer(self._conn, self.deliver_event)
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
        """Release what belongs to this session, by identity, and nothing else.

        One connection is shared by successive sessions of one identity: an old
        session dying and a new one reconnecting after its backoff address the same
        slot, and the old one may still be suspended here, awaiting its cancelled
        writer, long after its successor has completed an entire connect. So every
        removal compares first, and each piece of state is compared against the
        thing that owns it.

        The listener slot and its callbacks belong to *whoever holds the slot*, so
        they go only while ``self`` still does — the compare that keeps a
        superseded session from taking its successor's leg and entries, damage that
        would never heal because the successor keeps renewing its lease and goes on
        believing it is push-reachable while owning nothing. The two are released
        as one operation, because a callback whose listener has already gone is
        observable from the threads that route clicks and register entries.

        The writer and the subscriptions belong to *this session*: they are its own
        ``deliver_event``, so they are released on every path — including the one
        where a successor took the slot, and the one where the lease lapsed and the
        sweep took the session out from under a socket that lingered. Skipping them
        there left a dead session's ``deliver_event`` subscribed, and nothing could
        withdraw it — ``unsubscribe`` resolves the connection's *current* writer,
        which by then is the successor's — so every publish on the topic went on
        filling an outbound queue no write task drains, pinning the session and its
        socket for the life of the process.

        The bar is re-pushed whenever entries stopped being deliverable, and left
        alone only in the stale case, where a successor's entries are live. The
        session, its identity, its lease, and its hold survive: a reconnect within
        the lease drains the clicks buffered across the gap and re-registers from
        ``on_connect``, so a transient drop heals itself while a process that is
        gone stays gone.

        This method must contain no ``await``. With no suspension point the detach,
        the mark, and the release are one uninterrupted loop run, so no reconnect
        can interleave among them. Adding an ``await`` here reopens that window and
        invalidates the model this design was checked against.
        """
        detachment = self._clients.detach_listener(self._conn, self)
        if detachment in {"released_with_callbacks", "released_with_session"}:
            self._menus.mark_menus()
        self._hub.release_writer(self._conn, self.deliver_event)
