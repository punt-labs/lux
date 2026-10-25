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
from typing import TYPE_CHECKING, Literal, Self, final

from punt_lux.domain.hub.display_connection import DisplayConnection
from punt_lux.domain.hub.display_listener import DisplayListener
from punt_lux.domain.hub.display_requests import DisplayRequests
from punt_lux.domain.hub.handshake_connector import HandshakeConnector

if TYPE_CHECKING:
    from punt_lux.domain.hub.dial_generation import DialGeneration
    from punt_lux.domain.hub.display_dialer import DisplayDialer
    from punt_lux.domain.hub.event_port import EventPort

logger = logging.getLogger(__name__)

__all__ = ["DEFAULT_RECV_TIMEOUT", "DisplayLink"]

# The Hub-side budget for one display round-trip (ping / recv). A CLI reaching
# the display through luxd must keep its transport timeout above this.
DEFAULT_RECV_TIMEOUT = 5.0


@final
class DisplayLink:
    """Client for the Lux display server.

    A link dials through a ``dialer`` (a cross-host connector, say);
    :meth:`to_socket` makes the usual one, to the display's Unix socket.
    ``socket_path`` is the Unix socket path (``None`` uses the default).
    ``name`` is the identity this connection declares in its
    ``ConnectMessage``. ``kind="hub"`` triggers single-owner preemption plus
    a manifest (DES-068); ``"test"`` (default) is the read-only backdoor --
    a deliberately wrong-looking name, since the display rejects a
    ``SceneMessage`` sent under it. ``auto_spawn`` (default ``True``) spawns
    the display server when not running. ``connect_timeout`` bounds the wait
    for the display; ``recv_timeout`` is the default budget for a request's
    wait and for :meth:`~EventPort.poll_event`. A link over another dialer (a
    cross-host connector) is made with :meth:`over`.
    """

    _connection: DisplayConnection
    _listener: DisplayListener
    _requests: DisplayRequests

    def __new__(
        cls,
        dialer: DisplayDialer,
        *,
        connect_timeout: float = 5.0,
        recv_timeout: float = DEFAULT_RECV_TIMEOUT,
    ) -> Self:
        self = super().__new__(cls)
        self._connection = DisplayConnection(dialer, connect_timeout)
        self._listener = DisplayListener(self._connection, recv_timeout)
        self._requests = DisplayRequests(self._connection, self._listener, recv_timeout)
        return self

    @classmethod
    def to_socket(
        cls,
        socket_path: str | Path | None = None,
        *,
        name: str | None = None,
        kind: Literal["hub", "test"] = "test",
        auto_spawn: bool = True,
        connect_timeout: float = 5.0,
        recv_timeout: float = DEFAULT_RECV_TIMEOUT,
    ) -> Self:
        """Make a link to the display's Unix socket (the default path if ``None``)."""
        return cls(
            HandshakeConnector(
                name=name, kind=kind, socket_path=socket_path, auto_spawn=auto_spawn
            ),
            connect_timeout=connect_timeout,
            recv_timeout=recv_timeout,
        )

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

    def drop_if_current(self, generation: DialGeneration) -> bool:
        """Retire ``generation`` if it is still the current dial; whether it was.

        What a caller that saw its own dial fail asks for: it never closes a
        newer dial that replaced the one that failed.
        """
        return self._connection.close_if_current(generation, cause="hub")

    def connect(self, *, listen: bool = False) -> None:
        """Connect to the display server, and start the listener on the new dial.

        No-op if already connected.  If *auto_spawn* is enabled and no
        display is running, spawns one first.  Blocks until the
        ``ReadyMessage``/``ConnectMessage`` handshake completes (delegated to
        :class:`HandshakeConnector`, which owns the socket-open and identity
        concern). With ``listen`` the reader is started on the dial just opened,
        before anything is sent on it; if it cannot start, that dial is retired
        and the error raised, so the next connect redials.

        Raises
        ------
        DisplayNotConnectedError
            If the display fails to start or the handshake times out.
        """
        if not listen:
            self._connection.open()
            return
        dialed = self._connection.open_listening()
        if dialed is None:  # already connected: give it a reader if it lacks one
            self._listener.start()
            return
        try:
            self._listener.start_on(dialed)
        except BaseException:
            # A dial with no reader repairs nothing: retire the one this call made.
            self._connection.close_if_current(dialed, cause="hub")
            raise

    def close(self) -> None:
        """Close the connection to the display server."""
        self._listener.stop()
        self._connection.close()

    # -- ports -------------------------------------------------------------

    @property
    def requests(self) -> DisplayRequests:
        """What the Hub sends the display, and the answers it waits for."""
        return self._requests

    @property
    def events(self) -> EventPort:
        """What the display pushes: business events and interactions."""
        return self._listener
