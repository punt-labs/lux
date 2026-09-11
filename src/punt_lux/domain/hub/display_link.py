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

import contextlib
import logging
import queue
import select
import socket
import threading
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Self

from punt_lux.domain.hub.callback_key import CallbackKey
from punt_lux.domain.hub.handshake_connector import HandshakeConnector
from punt_lux.domain.hub.reply_queues import ReplyQueues
from punt_lux.polled_event import PolledEvent
from punt_lux.protocol import (
    AckMessage,
    CallbackMenuMessage,
    FrameReader,
    HubManifestMessage,
    MenuMessage,
    ObserverMessage,
    PingMessage,
    PongMessage,
    QueryRequest,
    QueryResponse,
    ReadyMessage,
    RemoteEventHandlerInvocation,
    SceneMessage,
    encode_message,
    recv_message,
)
from punt_lux.tracing import trace

if TYPE_CHECKING:
    from collections.abc import Generator

    from punt_lux.domain.hub.display_dialer import DisplayDialer
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

    _connect_timeout: float
    _recv_timeout: float
    _sock: socket.socket | None
    _ready: ReadyMessage | None
    _dialer: DisplayDialer
    _lock: threading.Lock
    _callbacks: dict[CallbackKey, Callable[[RemoteEventHandlerInvocation], None]]
    _fallback_interaction_handler: Callable[[RemoteEventHandlerInvocation], None] | None
    _listener_thread: threading.Thread | None
    _listener_stop: threading.Event
    _replies: ReplyQueues
    _event_queue: queue.SimpleQueue[PolledEvent]

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
        self._connect_timeout = connect_timeout
        self._recv_timeout = recv_timeout
        self._sock = None
        self._ready = None
        # An injected dialer (a cross-host CrossHostConnector built by
        # CrossHostEndpoint.dial) overrides the default; _dialer is never None.
        self._dialer = dialer or HandshakeConnector(
            name=name, kind=kind, socket_path=socket_path, auto_spawn=auto_spawn
        )
        self._lock = threading.Lock()
        self._callbacks = {}
        self._fallback_interaction_handler = None
        self._listener_thread = None
        self._listener_stop = threading.Event()
        self._replies = ReplyQueues()
        self._event_queue = queue.SimpleQueue()
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
        return self._sock is not None

    @property
    def listener_active(self) -> bool:
        """Whether the background listener thread is running."""
        return self._listener_thread is not None and self._listener_thread.is_alive()

    @property
    def ready_message(self) -> ReadyMessage | None:
        """The ``ReadyMessage`` received during handshake, or ``None``."""
        return self._ready

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
        if self._sock is not None:
            return

        result = self._dialer.dial(self._connect_timeout)
        self._sock = result.sock
        self._ready = result.ready

        if self._callbacks:  # reconnect resilience: restart a registered listener
            self.start_listener()

    def close(self) -> None:
        """Close the connection to the display server."""
        self.stop_listener()
        if self._sock is not None:
            with contextlib.suppress(OSError):
                self._sock.close()
            self._sock = None
            self._ready = None
            # A dying listener may still be mid-put; replacing the queue
            # outright (rather than draining it) can never race that put,
            # and any straggler it lands in is simply GC'd with the old queue.
            self._replies.drain()
            self._event_queue = queue.SimpleQueue()

    # -- callback registration ---------------------------------------------

    def set_fallback_handler(
        self,
        handler: Callable[[RemoteEventHandlerInvocation], None],
    ) -> None:
        """Install a fallback handler for unmatched interaction events.

        Called by the Hub to route display-side clicks through Hub-side
        element dispatch when no ``(element_id, action)`` callback matches.
        """
        self._fallback_interaction_handler = handler

    def on_event(
        self,
        key: CallbackKey,
        callback: Callable[[RemoteEventHandlerInvocation], None],
    ) -> None:
        """Register a callback for a ``(element_id, action)`` :class:`CallbackKey`.

        Callbacks are invoked by the background listener thread.  They
        may call :meth:`show_async` and other fire-and-forget methods
        but must not call blocking methods like :meth:`show`.

        If a callback raises an exception, the exception is logged and
        the event is consumed (not re-queued to pending).  This keeps
        the listener thread alive at the cost of dropping the event.

        Thread-safe: may be called while the listener is running.
        """
        with self._lock:
            self._callbacks[key] = callback

    def remove_callback(self, key: CallbackKey) -> None:
        """Remove the callback for ``key``, if any."""
        with self._lock:
            self._callbacks.pop(key, None)

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
        if self._listener_thread is not None and self._listener_thread.is_alive():
            return
        self._listener_stop.clear()
        self._listener_thread = threading.Thread(
            target=self._listener_loop,
            name="lux-listener",
            daemon=True,
        )
        self._listener_thread.start()

    def stop_listener(self) -> None:
        """Stop the background listener thread, if running."""
        t = self._listener_thread
        if t is None:
            return
        self._listener_stop.set()
        t.join(timeout=2.0)
        if t.is_alive():
            logger.warning("Listener thread did not exit within timeout")
        else:
            self._listener_thread = None

    def _listener_loop(self) -> None:
        """Background loop: read messages from socket, dispatch or buffer."""
        reader = FrameReader()
        while not self._listener_stop.is_set():
            sock = self._sock
            if sock is None:
                logger.debug("Listener exiting: socket is None")
                break
            try:
                readable, _, _ = select.select([sock], [], [], 0.1)
            except (OSError, ValueError) as exc:
                logger.warning("Listener exiting: select failed: %s", exc)
                break
            if not readable:
                continue
            with self._lock:
                try:
                    data = sock.recv(65536)
                except OSError as exc:
                    logger.warning("Listener exiting: recv failed: %s", exc)
                    break
            if not data:
                logger.debug("Listener exiting: server closed connection")
                break
            reader.feed(data)
            for msg in reader.drain_typed():
                self._dispatch(msg)

    def _dispatch(self, msg: Message) -> None:
        """Route a message to its typed destination.

        ``RemoteEventHandlerInvocation`` runs the registered callback for its
        ``(element_id, action)`` pair, falling back to
        :attr:`_fallback_interaction_handler` and then to a debug-logged
        drop.  ``ObserverMessage`` payloads queue for :meth:`poll_event`.
        ``AckMessage``, ``PongMessage``, and ``QueryResponse`` route to the
        per-type queues consumed by :meth:`show`, :meth:`ping`, and
        :meth:`query`.  Other message kinds are dropped with a debug log.
        """
        if isinstance(msg, RemoteEventHandlerInvocation):
            key = CallbackKey(msg.element_id, msg.action)
            with self._lock:
                cb = self._callbacks.get(key)
            if cb is None:
                fallback = self._fallback_interaction_handler
                if fallback is not None:
                    logger.debug(
                        "dispatch fallback element_id=%s action=%s scene_id=%s",
                        msg.element_id,
                        msg.action,
                        msg.scene_id,
                    )
                    with self._safely(
                        "Fallback handler error for %s:%s", msg.element_id, msg.action
                    ):
                        fallback(msg)
                else:
                    logger.debug(
                        "Dropping interaction with no callback: %s:%s",
                        msg.element_id,
                        msg.action,
                    )
                return
            with self._safely(
                "Callback error for %s:%s (event consumed)", msg.element_id, msg.action
            ):
                cb(msg)
            return
        if isinstance(msg, ObserverMessage):
            self._event_queue.put(PolledEvent(topic=msg.topic, payload=msg.payload))
            return
        if isinstance(msg, (AckMessage, PongMessage, QueryResponse)):
            self._replies.put(msg)
            return
        logger.debug("Dropping unhandled message: %s", type(msg).__name__)

    @staticmethod
    @contextlib.contextmanager
    def _safely(error_fmt: str, *log_args: object) -> Generator[None]:
        """Suppress and log any exception raised in the block, per *error_fmt*."""
        try:
            yield
        except Exception:
            logger.exception(error_fmt, *log_args)

    # -- sending -----------------------------------------------------------

    def _require_connected(self) -> socket.socket:
        if self._sock is None:
            msg = "Not connected — call connect() or use as context manager"
            raise RuntimeError(msg)
        return self._sock

    @trace
    def _send(self, sock: socket.socket, msg: Message) -> None:
        """Send a message on ``sock``, holding the lock when the listener is active.

        Takes the socket rather than fetching it via :meth:`_require_connected`
        itself: every caller is a public boundary method that already
        validates the connection to obtain ``sock``, so this internal
        primitive trusts that invariant instead of re-checking it (PY-EH-1).
        """
        wire = encode_message(msg)
        with self._lock:
            sock.sendall(wire)

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
        msg = SceneMessage(
            id=scene_id,
            elements=elements,
            title=title,
            layout=layout,
            frame_id=frame_id if frame_id is not None else scene_id,
            frame_title=frame_title,
            frame_size=frame_size,
            frame_flags=frame_flags,
            frame_layout=frame_layout,
        )
        self._send(self._require_connected(), msg)
        return self._recv_ack()

    def show_async(
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
    ) -> None:
        """Send a scene without waiting for ack (an omitted *frame_id* self-frames)."""
        msg = SceneMessage(
            id=scene_id,
            elements=elements,
            title=title,
            layout=layout,
            frame_id=frame_id if frame_id is not None else scene_id,
            frame_title=frame_title,
            frame_size=frame_size,
            frame_flags=frame_flags,
            frame_layout=frame_layout,
        )
        self._send(self._require_connected(), msg)

    def set_menu(self, menus: list[dict[str, Any]]) -> None:
        """Set custom menu bar entries."""
        self._send(self._require_connected(), MenuMessage(menus=menus))

    def set_callback_menus(self, submenus: list[dict[str, Any]]) -> None:
        """Replace the display's Clients menu (Hub-composed)."""
        self._send(self._require_connected(), CallbackMenuMessage(submenus=submenus))

    def send_manifest(self, scene_ids: Sequence[str]) -> None:
        """Declare the Hub's complete live-scene set to the display (DES-068).

        Meaningful only for a ``kind="hub"`` connection, sent immediately
        after identifying and before any scene content. The display purges
        every scene it cannot attribute to this connection that the
        manifest does not name.
        """
        self._send(
            self._require_connected(), HubManifestMessage(scene_ids=tuple(scene_ids))
        )

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
        self._send(self._require_connected(), PingMessage(ts=time.time()))
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
        self._send(
            self._require_connected(), QueryRequest(method=method, params=params or {})
        )
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
            return self._replies.get_typed(expected, timeout=max(remaining, 0))
        sock = self._require_connected()
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
        push-only). Gates on ``_listener_thread is not None`` so a listener
        that started and has since exited surfaces as ``TimeoutError`` naming
        the exit, not a ``RuntimeError`` claiming it never started.
        """
        self._require_connected()
        if self._listener_thread is None:
            err = (
                "poll_event requires an active listener — "
                "call start_listener() after connect()"
            )
            raise RuntimeError(err)
        t = timeout if timeout is not None else self._recv_timeout
        try:
            return self._event_queue.get(timeout=t)
        except queue.Empty as exc:
            if not self._listener_thread.is_alive():
                err = (
                    f"no business event arrived within {t}s "
                    "and the listener thread has exited"
                )
            else:
                err = f"no business event arrived within {t}s"
            raise TimeoutError(err) from exc

    def _ensure_not_listener_thread(self) -> None:
        """Raise if called from the listener thread (it would deadlock)."""
        if self._listener_thread is threading.current_thread():
            err = "Cannot call blocking _recv_ack from the listener thread"
            raise RuntimeError(err)

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
        self._ensure_not_listener_thread()
        if self.listener_active:
            return self._replies.get_ack(self._recv_timeout)
        sock = self._require_connected()
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
