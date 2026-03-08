"""Lux client library — connect to the display server and send scenes.

Provides :class:`LuxClient`, a context-manager that connects to the Lux
display server over a Unix domain socket, waits for the ``ReadyMessage``
handshake, and exposes typed methods for sending scenes, updates, clears,
and pings.  Receives ack, interaction, window, and pong events.

Usage::

    from punt_lux.client import LuxClient

    with LuxClient() as client:
        client.show("s1", elements=[TextElement(id="t1", content="Hello")])
        event = client.recv()
"""

from __future__ import annotations

import contextlib
import logging
import socket
import time
from collections import deque
from pathlib import Path
from typing import TYPE_CHECKING, Any

from punt_lux.paths import default_socket_path, ensure_display
from punt_lux.protocol import (
    AckMessage,
    ClearMessage,
    MenuMessage,
    PingMessage,
    PongMessage,
    ReadyMessage,
    SceneMessage,
    UpdateMessage,
    recv_message,
    send_message,
)

if TYPE_CHECKING:
    from punt_lux.protocol import Element, Message, Patch

logger = logging.getLogger(__name__)


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
        auto_spawn: bool = True,
        connect_timeout: float = 5.0,
        recv_timeout: float = 5.0,
    ) -> None:
        self._socket_path = Path(socket_path) if socket_path else None
        self._auto_spawn = auto_spawn
        self._connect_timeout = connect_timeout
        self._recv_timeout = recv_timeout
        self._sock: socket.socket | None = None
        self._ready: ReadyMessage | None = None
        self._pending: deque[Message] = deque()

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
    def ready_message(self) -> ReadyMessage | None:
        """The ``ReadyMessage`` received during handshake, or ``None``."""
        return self._ready

    def connect(self) -> None:
        """Connect to the display server.

        If *auto_spawn* is enabled and no display is running, spawns one
        first.  Blocks until the ``ReadyMessage`` handshake completes.

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

    def close(self) -> None:
        """Close the connection to the display server."""
        if self._sock is not None:
            with contextlib.suppress(OSError):
                self._sock.close()
            self._sock = None
            self._ready = None
            self._pending.clear()

    # -- sending -----------------------------------------------------------

    def _require_connected(self) -> socket.socket:
        if self._sock is None:
            msg = "Not connected — call connect() or use as context manager"
            raise RuntimeError(msg)
        return self._sock

    def show(
        self,
        scene_id: str,
        elements: list[Element],
        *,
        title: str | None = None,
        layout: str = "single",
        grid_columns: int | None = None,
    ) -> AckMessage | None:
        """Send a scene to the display and wait for acknowledgement.

        Returns the :class:`AckMessage` or ``None`` on timeout.
        """
        sock = self._require_connected()
        msg = SceneMessage(
            id=scene_id,
            elements=elements,
            title=title,
            layout=layout,
            grid_columns=grid_columns,
        )
        send_message(sock, msg)
        return self._recv_ack()

    def update(
        self,
        scene_id: str,
        patches: list[Patch],
    ) -> AckMessage | None:
        """Send incremental patches and wait for acknowledgement."""
        sock = self._require_connected()
        msg = UpdateMessage(scene_id=scene_id, patches=patches)
        send_message(sock, msg)
        return self._recv_ack()

    def set_menu(self, menus: list[dict[str, Any]]) -> None:
        """Set custom menu bar entries."""
        sock = self._require_connected()
        send_message(sock, MenuMessage(menus=menus))

    def clear(self) -> None:
        """Clear all content from the display."""
        sock = self._require_connected()
        send_message(sock, ClearMessage())

    def ping(self) -> PongMessage | None:
        """Send a ping and wait for the pong response."""
        sock = self._require_connected()
        send_message(sock, PingMessage(ts=time.time()))
        deadline = time.monotonic() + self._recv_timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            msg = recv_message(sock, timeout=remaining)
            if msg is None:
                return None
            if isinstance(msg, PongMessage):
                return msg
            self._pending.append(msg)

    # -- receiving ---------------------------------------------------------

    def recv(self, timeout: float | None = None) -> Message | None:
        """Receive the next message from the display.

        Returns buffered messages first, then reads from the socket.
        Returns ``None`` on timeout.
        """
        if self._pending:
            return self._pending.popleft()
        sock = self._require_connected()
        t = timeout if timeout is not None else self._recv_timeout
        return recv_message(sock, timeout=t)

    def _recv_ack(self) -> AckMessage | None:
        """Receive expecting an AckMessage.  Buffers non-ack messages.

        Reads directly from the socket until an AckMessage arrives or the
        timeout elapses, so that previously buffered non-ack messages do
        not prevent seeing a newer AckMessage on the wire.
        """
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
            self._pending.append(msg)
