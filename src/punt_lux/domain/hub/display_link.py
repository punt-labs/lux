"""The Hub's connection to the display process.

:class:`DisplayLink` coordinates one dial's lifecycle across its parts: it opens
the dial (the ``ReadyMessage`` handshake), starts and stops the listener on it,
and closes it. What the Hub sends and waits for is
:attr:`~DisplayLink.requests`; what the display pushes (business events,
interactions) is :attr:`~DisplayLink.events`. Each is a port: callers use that one
object's surface.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Self

from punt_lux.domain.hub.display_connection import DisplayConnection
from punt_lux.domain.hub.display_listener import DisplayListener
from punt_lux.domain.hub.display_requests import DisplayRequests
from punt_lux.domain.hub.handshake_connector import HandshakeConnector
from punt_lux.protocol import ReadyMessage

if TYPE_CHECKING:
    from punt_lux.domain.hub.display_dialer import DisplayDialer

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

    _connection: DisplayConnection
    _listener: DisplayListener
    _requests: DisplayRequests

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
        # An injected dialer (a cross-host CrossHostConnector built by
        # CrossHostEndpoint.dial) overrides the default AF_UNIX one.
        self._connection = DisplayConnection(
            dialer
            or HandshakeConnector(
                name=name, kind=kind, socket_path=socket_path, auto_spawn=auto_spawn
            ),
            connect_timeout,
        )
        self._listener = DisplayListener(self._connection, recv_timeout)
        self._requests = DisplayRequests(self._connection, self._listener, recv_timeout)
        return self

    # -- context manager ---------------------------------------------------

    def __enter__(self) -> DisplayLink:
        self._connection.open()
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
        return self._listener.listening

    @property
    def ready_message(self) -> ReadyMessage | None:
        """The ``ReadyMessage`` received during handshake, or ``None``."""
        return self._connection.ready

    def connect(self, *, listen: bool = False) -> None:
        """Connect to the display server, and start the listener on the new dial.

        No-op if already connected.  If *auto_spawn* is enabled and no
        display is running, spawns one first.  Blocks until the
        ``ReadyMessage``/``ConnectMessage`` handshake completes (delegated to
        :class:`HandshakeConnector`, which owns the socket-open and identity
        concern). With ``listen`` the reader is started on the dial just opened,
        before anything is sent on it.

        Raises
        ------
        DisplayNotConnectedError
            If the display fails to start or the handshake times out.
        """
        dialed = self._connection.open(listening=listen)
        if listen:
            self._listener.start(born_claimed=dialed)

    def close(self) -> None:
        """Close the connection to the display server."""
        self._listener.stop()
        self._connection.close()

    # -- background listener -----------------------------------------------

    def start_listener(self) -> None:
        """Start the background listener thread on the current dial.

        The listener reads what the display sends and routes it: interactions to
        the fallback handler, business events to :attr:`events`' queue, replies to
        the request that waits for them. Safe to call multiple times: a no-op if
        the current dial already has a reader. Raises
        :class:`ConnectionClosedError` if not connected.
        """
        self._listener.start()

    def stop_listener(self) -> None:
        """Stop the background listener thread, if running, and retire its dial.

        A reader lives and dies with its dial: a caller that stops its listener
        and wants another must reconnect first.
        """
        self._listener.stop()

    # -- ports -------------------------------------------------------------

    @property
    def requests(self) -> DisplayRequests:
        """What the Hub sends the display, and the answers it waits for."""
        return self._requests

    @property
    def events(self) -> DisplayListener:
        """What the display pushes: business events and interactions."""
        return self._listener
