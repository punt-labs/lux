"""Lux client library — connect to the display server and send scenes.

Provides :class:`LuxClient`, a context-manager that connects to the Lux
display server over a Unix domain socket, waits for the ``ReadyMessage``
handshake, and exposes typed methods for sending scenes, updates, clears,
and pings.  Receives ack, interaction, window, and pong events.

Supports push-based event handling via :meth:`on_event` and
:meth:`start_listener`.  When the background listener is active, incoming
messages with registered callbacks are dispatched automatically; all other
messages (including acks) are buffered for the main thread.

Usage::

    from punt_lux.client import LuxClient

    with LuxClient() as client:
        client.show("s1", elements=[TextElement(id="t1", content="Hello")])
        event = client.recv()
"""

from __future__ import annotations

import contextlib
import logging
import queue
import select
import socket
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from punt_lux.paths import default_socket_path, ensure_display
from punt_lux.protocol import (
    AckMessage,
    ClearMessage,
    ConnectMessage,
    FrameReader,
    InteractionMessage,
    MenuMessage,
    PingMessage,
    PongMessage,
    ReadyMessage,
    RegisterMenuMessage,
    SceneMessage,
    ThemeMessage,
    UpdateMessage,
    encode_message,
    recv_message,
    send_message,
)

if TYPE_CHECKING:
    from punt_lux.protocol import Element, Message, Patch

logger = logging.getLogger(__name__)


def _drain_queue(q: queue.SimpleQueue[Any]) -> None:
    """Discard all items from a :class:`queue.SimpleQueue`."""
    while True:
        try:
            q.get_nowait()
        except queue.Empty:
            break


class LuxClient:
    """Client for the Lux display server.

    Parameters
    ----------
    socket_path:
        Path to the Unix domain socket.  ``None`` uses the default.
    auto_spawn:
        If ``True`` (default), spawn the display server when not running.
    connect_timeout:
        Seconds to wait for the display to become available.
    recv_timeout:
        Default timeout in seconds for :meth:`recv`.
    """

    def __init__(
        self,
        socket_path: str | Path | None = None,
        *,
        name: str | None = None,
        auto_spawn: bool = True,
        connect_timeout: float = 5.0,
        recv_timeout: float = 5.0,
    ) -> None:
        self._socket_path = Path(socket_path) if socket_path else None
        self._name = name
        self._auto_spawn = auto_spawn
        self._connect_timeout = connect_timeout
        self._recv_timeout = recv_timeout
        self._sock: socket.socket | None = None
        self._ready: ReadyMessage | None = None
        self._pending: queue.SimpleQueue[Message] = queue.SimpleQueue()
        self._registered_menu_items: list[dict[str, Any]] = []

        # Push-based event handling state
        self._lock = threading.Lock()
        self._callbacks: dict[
            tuple[str, str], Callable[[InteractionMessage], None]
        ] = {}
        self._listener_thread: threading.Thread | None = None
        self._listener_stop = threading.Event()
        self._ack_queue: queue.SimpleQueue[AckMessage] = queue.SimpleQueue()
        self._pong_queue: queue.SimpleQueue[PongMessage] = queue.SimpleQueue()

    # -- context manager ---------------------------------------------------

    def __enter__(self) -> LuxClient:
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

        If *auto_spawn* is enabled and no display is running, spawns one
        first.  Blocks until the ``ReadyMessage`` handshake completes.
        If callbacks are registered, restarts the background listener.

        Raises
        ------
        RuntimeError
            If the display fails to start or the handshake times out.
        """
        if self._sock is not None:
            return

        path = self._socket_path or default_socket_path()

        if self._auto_spawn:
            path = ensure_display(path, timeout=self._connect_timeout)

        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            sock.connect(str(path))
        except (ConnectionRefusedError, FileNotFoundError, OSError) as exc:
            sock.close()
            msg = f"Cannot connect to display at {path}: {exc}"
            raise RuntimeError(msg) from exc

        self._sock = sock
        self._socket_path = path

        try:
            ready = recv_message(sock, timeout=self._connect_timeout)
        except Exception:
            self.close()
            raise
        if ready is None:
            self.close()
            msg = f"Handshake timed out after {self._connect_timeout}s at {path}"
            raise RuntimeError(msg)
        if not isinstance(ready, ReadyMessage):
            self.close()
            msg = f"Expected ReadyMessage, got {type(ready).__name__}"
            raise RuntimeError(msg)
        self._ready = ready
        logger.info("Connected to display (protocol %s)", ready.version)
        self._post_handshake(sock)

        # Restart listener if callbacks are registered (reconnect resilience)
        if self._callbacks:
            self.start_listener()

    def _post_handshake(self, sock: socket.socket) -> None:
        """Send identity and replay registrations after handshake."""
        if self._name:
            try:
                send_message(sock, ConnectMessage(name=self._name))
            except OSError as exc:
                self.close()
                err = f"ConnectMessage failed after handshake: {exc}"
                raise RuntimeError(err) from exc
        if self._registered_menu_items:
            try:
                replay = RegisterMenuMessage(items=self._registered_menu_items)
                send_message(sock, replay)
            except OSError as exc:
                self.close()
                err = f"Menu replay failed after handshake: {exc}"
                raise RuntimeError(err) from exc

    def close(self) -> None:
        """Close the connection to the display server."""
        self.stop_listener()
        if self._sock is not None:
            with contextlib.suppress(OSError):
                self._sock.close()
            self._sock = None
            self._ready = None
            _drain_queue(self._pending)
            _drain_queue(self._ack_queue)
            _drain_queue(self._pong_queue)

    # -- callback registration ---------------------------------------------

    def on_event(
        self,
        element_id: str,
        action: str,
        callback: Callable[[InteractionMessage], None],
    ) -> None:
        """Register a callback for ``(element_id, action)`` events.

        Callbacks are invoked by the background listener thread.  They
        may call :meth:`show_async` and other fire-and-forget methods
        but must not call blocking methods like :meth:`show`.

        If a callback raises an exception, the exception is logged and
        the event is consumed (not re-queued to pending).  This keeps
        the listener thread alive at the cost of dropping the event.

        Register callbacks before calling :meth:`start_listener`.
        """
        self._callbacks[(element_id, action)] = callback

    def remove_callback(self, element_id: str, action: str) -> None:
        """Remove the callback for ``(element_id, action)``, if any."""
        self._callbacks.pop((element_id, action), None)

    # -- background listener -----------------------------------------------

    def start_listener(self) -> None:
        """Start the background listener thread.

        The listener reads incoming messages from the socket and
        dispatches interaction events to registered callbacks.
        Unmatched events go to ``_pending``; acks go to ``_ack_queue``.

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
        if self._listener_thread is None:
            return
        self._listener_stop.set()
        self._listener_thread.join(timeout=2.0)
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
                self._dispatch_or_buffer(msg)

    def _dispatch_or_buffer(self, msg: Message) -> None:
        """Route a message to the right destination.

        Interaction events with a registered callback are dispatched
        immediately on the listener thread.  Acks and pongs go to
        dedicated queues; everything else goes to the general pending
        queue for :meth:`recv`.
        """
        if isinstance(msg, InteractionMessage):
            key = (msg.element_id, msg.action)
            cb = self._callbacks.get(key)
            if cb is not None:
                try:
                    cb(msg)
                except Exception:
                    logger.exception(
                        "Callback error for %s:%s (event consumed)",
                        msg.element_id,
                        msg.action,
                    )
                return
        if isinstance(msg, AckMessage):
            self._ack_queue.put(msg)
            return
        if isinstance(msg, PongMessage):
            self._pong_queue.put(msg)
            return
        self._pending.put(msg)

    # -- sending -----------------------------------------------------------

    def _require_connected(self) -> socket.socket:
        if self._sock is None:
            msg = "Not connected — call connect() or use as context manager"
            raise RuntimeError(msg)
        return self._sock

    def _send(self, msg: Message) -> None:
        """Send a message, holding the lock when the listener is active."""
        sock = self._require_connected()
        wire = encode_message(msg)
        with self._lock:
            sock.sendall(wire)

    def show(
        self,
        scene_id: str,
        elements: list[Element],
        *,
        title: str | None = None,
        layout: str = "single",
        grid_columns: int | None = None,
        frame_id: str | None = None,
        frame_title: str | None = None,
        frame_size: tuple[int, int] | None = None,
        frame_flags: dict[str, bool] | None = None,
    ) -> AckMessage | None:
        """Send a scene to the display and wait for acknowledgement.

        When *frame_id* is provided, the scene is rendered inside a named
        frame (an ImGui inner window).  The frame is created on first use.

        Returns the :class:`AckMessage` or ``None`` on timeout.
        """
        msg = SceneMessage(
            id=scene_id,
            elements=elements,
            title=title,
            layout=layout,
            grid_columns=grid_columns,
            frame_id=frame_id,
            frame_title=frame_title,
            frame_size=frame_size,
            frame_flags=frame_flags,
        )
        self._send(msg)
        return self._recv_ack()

    def show_async(
        self,
        scene_id: str,
        elements: list[Element],
        *,
        title: str | None = None,
        layout: str = "single",
        grid_columns: int | None = None,
        frame_id: str | None = None,
        frame_title: str | None = None,
        frame_size: tuple[int, int] | None = None,
        frame_flags: dict[str, bool] | None = None,
    ) -> None:
        """Send a scene without waiting for ack.  Safe to call from callbacks."""
        msg = SceneMessage(
            id=scene_id,
            elements=elements,
            title=title,
            layout=layout,
            grid_columns=grid_columns,
            frame_id=frame_id,
            frame_title=frame_title,
            frame_size=frame_size,
            frame_flags=frame_flags,
        )
        self._send(msg)

    def update(
        self,
        scene_id: str,
        patches: list[Patch],
    ) -> AckMessage | None:
        """Send incremental patches and wait for acknowledgement."""
        msg = UpdateMessage(scene_id=scene_id, patches=patches)
        self._send(msg)
        return self._recv_ack()

    def update_async(
        self,
        scene_id: str,
        patches: list[Patch],
    ) -> None:
        """Send incremental patches without waiting for ack.  Safe from callbacks."""
        msg = UpdateMessage(scene_id=scene_id, patches=patches)
        self._send(msg)

    def set_menu(self, menus: list[dict[str, Any]]) -> None:
        """Set custom menu bar entries."""
        self._send(MenuMessage(menus=menus))

    def set_theme(self, theme: str) -> None:
        """Set the display theme by name (e.g. 'imgui_colors_light')."""
        self._send(ThemeMessage(theme=theme))

    def _store_menu_item(self, item: dict[str, Any]) -> None:
        """Add or update an item in the local menu registry (no send)."""
        stored = dict(item)
        item_id = item.get("id")
        if item_id is not None:
            for idx, existing in enumerate(self._registered_menu_items):
                if existing.get("id") == item_id:
                    self._registered_menu_items[idx] = stored
                    return
            self._registered_menu_items.append(stored)
        else:
            self._registered_menu_items.append(stored)

    def declare_menu_item(self, item: dict[str, Any]) -> None:
        """Declare a menu item without requiring a connection.

        The item is stored locally and sent to the display on the
        next ``connect()`` via ``_post_handshake``.  Safe to call
        before ``connect()``.
        """
        self._store_menu_item(item)

    def register_menu_item(self, item: dict[str, Any]) -> None:
        """Register a menu item in the display's Applications menu.

        Items accumulate and are sent as a single ``RegisterMenuMessage``.
        On reconnect, all registered items are automatically replayed.
        Requires an active connection.
        """
        self._store_menu_item(item)
        self._send(RegisterMenuMessage(items=self._registered_menu_items))

    def clear(self) -> None:
        """Clear all content from the display."""
        self._send(ClearMessage())

    def clear_async(self) -> None:
        """Clear all content from the display.  Safe from callbacks."""
        self._send(ClearMessage())

    def ping(self) -> PongMessage | None:
        """Send a ping and wait for the pong response."""
        self._send(PingMessage(ts=time.time()))
        deadline = time.monotonic() + self._recv_timeout
        if self.listener_active:
            remaining = deadline - time.monotonic()
            try:
                return self._pong_queue.get(timeout=max(remaining, 0))
            except queue.Empty:
                return None
        sock = self._require_connected()
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            received = recv_message(sock, timeout=remaining)
            if received is None:
                return None
            if isinstance(received, PongMessage):
                return received
            self._pending.put(received)

    # -- receiving ---------------------------------------------------------

    def recv(self, timeout: float | None = None) -> Message | None:
        """Receive the next message from the display.

        Thread-safe.  When the listener is active, blocks on the
        ``_pending`` queue.  When inactive, reads directly from the
        socket.  Returns ``None`` on timeout.
        """
        t = timeout if timeout is not None else self._recv_timeout
        if self.listener_active:
            try:
                return self._pending.get(timeout=t)
            except queue.Empty:
                return None
        try:
            return self._pending.get_nowait()
        except queue.Empty:
            pass
        sock = self._require_connected()
        return recv_message(sock, timeout=t)

    def _recv_ack(self) -> AckMessage | None:
        """Receive expecting an AckMessage.  Buffers non-ack messages.

        Thread-safe.  When the listener is active, blocks on
        ``_ack_queue``.  When inactive, reads directly from the socket.
        """
        if self.listener_active:
            try:
                return self._ack_queue.get(timeout=self._recv_timeout)
            except queue.Empty:
                return None
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
            self._pending.put(msg)
