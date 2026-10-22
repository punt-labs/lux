"""The Hub's connection to the display process.

:class:`DisplayLink` is a context manager over a Unix socket that performs
the ``ReadyMessage`` handshake and exposes typed methods for scenes, pings,
and queries. :meth:`on_event` + :meth:`start_listener` enable push-based
dispatch on the listener thread; acks, pongs, and query responses route to
the queues :meth:`show`, :meth:`ping`, and :meth:`query` consume, and
:class:`ObserverMessage` frames queue as :class:`PolledEvent` for
:meth:`poll_event`.
"""

from __future__ import annotations

import logging
import queue
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Self

from punt_lux.domain.hub.display_connection import DisplayConnection
from punt_lux.domain.hub.handshake_connector import HandshakeConnector
from punt_lux.domain.hub.inbound_router import InboundRouter
from punt_lux.domain.hub.interaction_handlers import InteractionHandlers
from punt_lux.domain.hub.listener_thread import ListenerThread
from punt_lux.domain.hub.scene_presentation import ScenePresentation
from punt_lux.protocol import (
    AckMessage,
    CallbackMenuMessage,
    HubManifestMessage,
    MenuMessage,
    PingMessage,
    PongMessage,
    QueryRequest,
    QueryResponse,
    ReadyMessage,
    RemoteEventHandlerInvocation,
    SceneMessage,
    recv_message,
)

if TYPE_CHECKING:
    from punt_lux.domain.hub.callback_key import CallbackKey
    from punt_lux.domain.hub.display_dialer import DisplayDialer
    from punt_lux.polled_event import PolledEvent
    from punt_lux.protocol import Element, Message

logger = logging.getLogger(__name__)

__all__ = ["DEFAULT_RECV_TIMEOUT", "DisplayLink"]

# The Hub-side budget for one display round-trip (ping / recv). A CLI reaching
# the display through luxd must keep its transport timeout above this.
DEFAULT_RECV_TIMEOUT = 5.0


class DisplayLink:
    """Client for the Lux display server.

    ``socket_path`` is the Unix socket path (``None`` uses the default).
    ``name`` is the identity this connection declares in its
    ``ConnectMessage``. ``kind="hub"`` triggers single-owner preemption plus
    a manifest (DES-068); ``"test"`` (default) is the read-only backdoor --
    a deliberately wrong-looking name, since the display rejects a
    ``SceneMessage`` sent under it. ``auto_spawn`` (default ``True``) spawns
    the display server when not running. ``connect_timeout`` bounds the wait
    for the display; ``recv_timeout`` is the default for :meth:`recv`.
    """

    _recv_timeout: float
    _connection: DisplayConnection
    _listener: ListenerThread
    _handlers: InteractionHandlers
    _inbound: InboundRouter

    def __new__(
        cls,
        socket_path: str | Path | None = None,
        *,
        name: str | None = None,
        kind: Literal["hub", "test"] = "test",
        auto_spawn: bool = True,
        connect_timeout: float = 5.0,
        recv_timeout: float = DEFAULT_RECV_TIMEOUT,
        dialer: DisplayDialer | None = None,  # None = default AF_UNIX dialer (PY-TS-14)
    ) -> Self:
        self = super().__new__(cls)
        self._recv_timeout = recv_timeout
        # An injected dialer (a cross-host CrossHostConnector built by
        # CrossHostEndpoint.dial) overrides the default AF_UNIX one.
        self._connection = DisplayConnection(
            dialer
            or HandshakeConnector(
                name=name, kind=kind, socket_path=socket_path, auto_spawn=auto_spawn
            ),
            connect_timeout,
        )
        self._handlers = InteractionHandlers()
        self._inbound = InboundRouter(self._handlers)
        self._listener = ListenerThread(self._connection, self._inbound.route)
        return self

    # -- context manager ---------------------------------------------------

    def __enter__(self) -> DisplayLink:
        self.connect()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    # -- connection --------------------------------------------------------

    @property
    def is_connected(self) -> bool:
        """Whether the client has an active socket connection."""
        return self._connection.is_open

    @property
    def listener_active(self) -> bool:
        """Whether the background listener thread is running."""
        return self._listener.alive

    @property
    def ready_message(self) -> ReadyMessage | None:
        """The ``ReadyMessage`` received during handshake, or ``None``."""
        return self._connection.ready

    def connect(self) -> None:
        """Connect to the display server.

        No-op if already connected.  If *auto_spawn* is enabled and no
        display is running, spawns one first.  Blocks until the
        ``ReadyMessage``/``ConnectMessage`` handshake completes (delegated to
        :class:`HandshakeConnector`, which owns the socket-open and identity
        concern). If callbacks are registered, starts the background
        listener after handshake.

        Raises
        ------
        DisplayNotConnectedError
            If the display fails to start or the handshake times out.
        """
        if self._connection.is_open:
            return
        self._connection.open()
        # Reconnect resilience: restart the listener if callbacks are registered.
        if self._handlers.any_registered:
            self.start_listener()

    def close(self) -> None:
        """Close the connection to the display server."""
        self.stop_listener()
        if self._connection.is_open:
            self._connection.close()
            self._inbound.reset()

    # -- callback registration ---------------------------------------------

    def set_fallback_handler(
        self,
        handler: Callable[[RemoteEventHandlerInvocation], None],
    ) -> None:
        """Install a fallback handler for unmatched interaction events.

        Called by the Hub to route display-side clicks through Hub-side
        element dispatch when no ``(element_id, action)`` callback matches.
        """
        self._handlers.set_fallback(handler)

    def on_event(
        self,
        key: CallbackKey,
        callback: Callable[[RemoteEventHandlerInvocation], None],
    ) -> None:
        """Register a callback for a ``(element_id, action)`` :class:`CallbackKey`.

        Callbacks are invoked by the background listener thread.  They
        may call :meth:`send_scene` and other fire-and-forget methods
        but must not call blocking methods like :meth:`show`.

        If a callback raises an exception, the exception is logged and
        the event is consumed (not re-queued to pending).  This keeps
        the listener thread alive at the cost of dropping the event.

        Thread-safe: may be called while the listener is running.
        """
        self._handlers.register(key, callback)

    def remove_callback(self, key: CallbackKey) -> None:
        """Remove the callback for ``key``, if any."""
        self._handlers.remove(key)

    # -- background listener -----------------------------------------------

    def start_listener(self) -> None:
        """Start the background listener thread.

        The listener reads incoming messages from the socket and
        dispatches them by kind: ``RemoteEventHandlerInvocation`` runs the
        registered ``(element_id, action)`` callback (unmatched
        interactions are dropped); ``ObserverMessage`` payloads queue
        for :meth:`poll_event`; ``AckMessage``, ``PongMessage``, and
        ``QueryResponse`` route to their per-type queues for
        :meth:`show`, :meth:`ping`, and :meth:`query`.  Other message
        kinds are dropped with a debug log.

        Safe to call multiple times — no-ops if already running.
        """
        self._listener.start()

    def stop_listener(self) -> None:
        """Stop the background listener thread, if running."""
        self._listener.stop()

    # -- sending -----------------------------------------------------------

    def show(
        self,
        scene_id: str,
        elements: list[Element],
        *,
        title: str | None = None,
        layout: Literal["single", "rows", "columns", "grid"] = "single",
        frame_id: str | None = None,
        frame_title: str | None = None,
        frame_size: tuple[int, int] | None = None,
        frame_flags: dict[str, bool] | None = None,
        frame_layout: Literal["tab", "stack"] | None = None,
    ) -> AckMessage | None:
        """Send a scene to the display and wait for acknowledgement.

        Every scene is framed: an omitted *frame_id* self-frames by *scene_id* (as
        the Hub does), so a bare ``show`` still lands in a named frame. Returns the
        :class:`AckMessage` or ``None`` on timeout.
        """
        presentation = ScenePresentation(
            frame_id=frame_id if frame_id is not None else scene_id,
            title=title,
            layout=layout,
            frame_title=frame_title,
            frame_size=frame_size,
            frame_flags=frame_flags,
            frame_layout=frame_layout,
        )
        self.send_scene(presentation.message(scene_id, elements))
        return self._recv_ack()

    def send_scene(self, message: SceneMessage) -> None:
        """Send a built scene without waiting for an ack."""
        self._connection.send(message)

    def set_menu(self, menus: list[dict[str, Any]]) -> None:
        """Set custom menu bar entries."""
        self._connection.send(MenuMessage(menus=menus))

    def set_callback_menus(self, submenus: list[dict[str, Any]]) -> None:
        """Replace the display's Clients menu (Hub-composed)."""
        self._connection.send(CallbackMenuMessage(submenus=submenus))

    def send_manifest(self, scene_ids: Sequence[str]) -> None:
        """Declare the Hub's complete live-scene set to the display (DES-068).

        Meaningful only for a ``kind="hub"`` connection, sent immediately
        after identifying and before any scene content. The display purges
        every scene it cannot attribute to this connection that the
        manifest does not name.
        """
        self._connection.send(HubManifestMessage(scene_ids=tuple(scene_ids)))

    def probe_alive(self, timeout: float) -> bool:
        """Return whether the display responded to a ping within ``timeout``.

        The :class:`DisplaySender` liveness probe the replicator's isolation
        loop calls between successive singleton sends, so a crash caused by
        scene N attributes to N (not N+1). A None pong (timed out) or any
        socket error the underlying send raises means the display did not
        respond in time; the caller treats that as a failure of the scene
        just sent.
        """
        return self.ping(timeout=timeout) is not None

    def ping(self, timeout: float | None = None) -> PongMessage | None:
        """Send a ping and wait for the pong within ``timeout`` (else recv budget)."""
        self._connection.send(PingMessage(ts=time.time()))
        budget = timeout if timeout is not None else self._recv_timeout
        return self._await_typed(PongMessage, time.monotonic() + budget)

    def query(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> QueryResponse | None:
        """Send a generic query and wait for the response."""
        budget = timeout if timeout is not None else self._recv_timeout
        self._connection.send(QueryRequest(method=method, params=params or {}))
        return self._await_typed(QueryResponse, time.monotonic() + budget)

    def _await_typed[T: Message](self, expected: type[T], deadline: float) -> T | None:
        """Wait for one ``expected`` reply, active listener or inline read.

        Shared by :meth:`ping` and :meth:`query`: both send a request and then
        wait for exactly one typed reply -- from the background listener's own
        queue when it is running, or an inline read loop when it is not,
        dropping any interleaved frame the inline path sees along the way.
        """
        if self.listener_active:
            remaining = deadline - time.monotonic()
            return self._inbound.next_reply(expected, max(remaining, 0))
        sock = self._connection.require()
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            received = recv_message(sock, timeout=remaining)
            if received is None:
                return None
            if isinstance(received, expected):
                return received
            kind = type(received).__name__
            logger.debug("%s: dropping interleaved %s frame", expected.__name__, kind)

    # -- receiving ---------------------------------------------------------

    def poll_event(self, timeout: float | None = None) -> PolledEvent:
        """Block for the next subscribed business event (a :class:`PolledEvent`).

        Raises ``TimeoutError`` after ``timeout`` seconds (default
        ``recv_timeout``); requires an active listener (observer messages are
        push-only). Gates on the listener having started so a listener
        that started and has since exited surfaces as ``TimeoutError`` naming
        the exit, not a ``RuntimeError`` claiming it never started.
        """
        self._connection.require()
        if not self._listener.started:
            err = (
                "poll_event requires an active listener — "
                "call start_listener() after connect()"
            )
            raise RuntimeError(err)
        t = timeout if timeout is not None else self._recv_timeout
        try:
            return self._inbound.next_event(t)
        except queue.Empty as exc:
            if not self._listener.alive:
                err = (
                    f"no business event arrived within {t}s "
                    "and the listener thread has exited"
                )
            else:
                err = f"no business event arrived within {t}s"
            raise TimeoutError(err) from exc

    def _recv_ack(self) -> AckMessage | None:
        """Receive expecting an AckMessage.  Drops interleaved frames.

        Thread-safe.  When the listener is active, blocks on the reply
        queues.  When inactive, reads directly from the socket
        and drops any non-ack frame that arrives in the meantime —
        each typed reader (poll_event / ping / query) owns its own
        path, so there is no shared backlog to push into.

        Raises RuntimeError if called from the listener thread (would
        deadlock because the listener is the only ack producer).
        """
        if self._listener.is_current:
            err = "Cannot call blocking _recv_ack from the listener thread"
            raise RuntimeError(err)
        if self.listener_active:
            return self._inbound.next_ack(self._recv_timeout)
        sock = self._connection.require()
        deadline = time.monotonic() + self._recv_timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            msg = recv_message(sock, timeout=remaining)
            if msg is None:
                return None
            if isinstance(msg, AckMessage):
                return msg
            logger.debug("_recv_ack: dropping interleaved %s frame", type(msg).__name__)
