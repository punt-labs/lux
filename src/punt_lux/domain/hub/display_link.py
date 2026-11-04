"""The Hub's connection to the display process.

:class:`DisplayLink` coordinates one dial's lifecycle across its parts: it opens
the dial (the ``ReadyMessage`` handshake), starts and stops the listener on it,
and closes it. What the Hub asks and waits for, and the one seat writers are made
at, is :attr:`~DisplayLink.desk`; what the display pushes (business events,
interactions) is :attr:`~DisplayLink.events`. The manifest that
declares what the Hub holds is written inside :meth:`~DisplayLink.open_as_hub`, the
link's own connect step for the Hub, and nowhere else.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Self, final

from punt_lux.domain.hub.display_connection import DisplayConnection
from punt_lux.domain.hub.display_listener import DisplayListener
from punt_lux.domain.hub.handshake_connector import HandshakeConnector
from punt_lux.domain.hub.request_desk import RequestDesk

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from punt_lux.domain.hub.connection_closed import RetireCause
    from punt_lux.domain.hub.death_queue import DeathQueue
    from punt_lux.domain.hub.dial_ref import DialRef
    from punt_lux.domain.hub.display_dialer import DisplayDialer
    from punt_lux.domain.hub.event_port import EventPort
    from punt_lux.domain.ids import SceneId

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
    ``connect_timeout`` bounds the wait for the display; ``recv_timeout`` is the
    default budget for a request's wait and for
    :meth:`~punt_lux.domain.hub.event_port.EventPort.poll_event`.
    """

    _connection: DisplayConnection
    _listener: DisplayListener
    _desk: RequestDesk

    def __new__(
        cls,
        dialer: DisplayDialer,
        *,
        connect_timeout: float = 5.0,
        recv_timeout: float = DEFAULT_RECV_TIMEOUT,
    ) -> Self:
        self = super().__new__(cls)
        self._connection = DisplayConnection(
            dialer,
            connect_timeout,
            # An ended dial is settled by the holder of its reader slot, or by whoever
            # found it ended if no one holds it; the listener, which owns the readers,
            # knows how to ask.
            ask_settle=lambda generation, cause: self._listener.ask_settle(
                generation, cause
            ),
        )
        self._listener = DisplayListener(self._connection, recv_timeout)
        self._desk = RequestDesk(self._connection, self._listener, recv_timeout)
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
        """Make a link to the display's Unix socket (the default path if ``None``).

        ``name`` is the identity the connection declares in its
        ``ConnectMessage``. ``kind="hub"`` triggers single-owner preemption plus
        a manifest (DES-068); ``"test"`` (default) is the read-only backdoor -- a
        deliberately wrong-looking name, since the display rejects a
        ``SceneMessage`` sent under it. ``auto_spawn`` (default ``True``) spawns
        the display server when it is not running.
        """
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

    def drop_if_current(self, dial: DialRef, *, cause: RetireCause) -> bool:
        """Retire ``dial`` if it is still the current dial; whether it was.

        What a caller that saw its own dial fail asks for: it never closes a
        newer dial that replaced the one that failed. ``cause`` says who ended it,
        for whoever finds it gone.
        """
        return dial.retire_in(self._connection, cause=cause)

    def connect(self, *, listen: bool = False) -> None:
        """Connect to the display server, and start the listener on the new dial.

        No-op if already connected.  If *auto_spawn* is enabled and no
        display is running, spawns one first.  Blocks until the
        ``ReadyMessage``/``ConnectMessage`` handshake completes (delegated to
        :class:`HandshakeConnector`, which owns the socket-open and identity
        concern). With ``listen`` the reader is started on the dial just opened,
        before anything is sent on it; if it cannot start, that dial is retired
        and the error raised, so the next connect redials. This link writes no
        manifest: that is :meth:`open_as_hub`.

        Raises
        ------
        DisplayNotConnectedError
            If the display fails to start or the handshake times out.
        """
        if not listen:
            self._connection.open()
        elif (dialed := self._connection.open_listening()) is None:
            self._listener.start()  # connected already: a reader, if it lacks one
        else:
            self._listener.start_on(dialed)

    def open_as_hub(
        self, manifest: Callable[[], Sequence[SceneId]]
    ) -> tuple[SceneId, ...]:
        """Connect with a reader, then declare what the Hub holds (DES-068).

        The manifest is read once the dial is up, and its scene ids are written as the
        manifest: the second half of opening the connection, before anything else is
        sent on it. Declares only on a dial this call made, which is what the dial's
        own opening reports; a link already open returns ``()``. A manifest that
        cannot be sent closes the link and raises, so the next call redials and
        declares again. Returns the scene ids declared.
        """
        dialed = self._connection.open_listening()
        if dialed is None:
            self._listener.start()  # connected already: a reader, if it lacks one
            return ()
        self._listener.start_on(dialed)
        scene_ids = tuple(manifest())
        try:
            self._desk.declare(scene_ids)
        except OSError:
            self.close()
            raise
        return scene_ids

    def close(self) -> None:
        """Close the connection to the display server."""
        self._listener.stop()
        self._connection.close()

    def take_deaths(self) -> DeathQueue:
        """The queue of display deaths not yet charged, handed out once."""
        return self._connection.take_deaths()

    @property
    def desk(self) -> RequestDesk:
        """Where requests are made: the asks, and the one write seat."""
        return self._desk

    @property
    def events(self) -> EventPort:
        """What the display pushes: business events and interactions."""
        return self._listener
