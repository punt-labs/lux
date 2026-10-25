"""DisplayConnection -- which dial is current, and every write onto it.

The connection dials the display and says which :class:`DialGeneration` is current;
the generation owns its socket, its writes, its reader's bytes and the replies it
is owed, and reports its own breakage back through :meth:`close_if_current`. A
state lock, distinct from every generation's socket lock, guards the current
generation and is held only for a field update, never across a dial, a write or a
close. Retiring a generation is :meth:`close_if_current`: a no-op unless that
generation is still current, so a reader or a waiter that outlived a redial can
report its own dial's end without touching the new one.

The link's typed calls, the reader and the request waits are clients of it and
share no socket state of their own.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.hub.connection_closed import ConnectionClosedError
from punt_lux.domain.hub.dial_generation import DialGeneration

if TYPE_CHECKING:
    from punt_lux.domain.hub.display_dialer import DisplayDialer
    from punt_lux.protocol import ReadyMessage

__all__ = ["DisplayConnection"]


@final
class DisplayConnection:
    """The current dial to the display: dialed on open, retired on close."""

    _dialer: DisplayDialer
    _connect_timeout: float
    _state_lock: threading.Lock
    # None = not connected. The generation holds the socket, its endpoint and its
    # ready message: one handshake's result, coming and going together.
    _current: DialGeneration | None
    __slots__ = ("_connect_timeout", "_current", "_dialer", "_state_lock")

    def __new__(cls, dialer: DisplayDialer, connect_timeout: float) -> Self:
        self = super().__new__(cls)
        self._dialer = dialer
        self._connect_timeout = connect_timeout
        self._state_lock = threading.Lock()
        self._current = None
        return self

    @property
    def is_open(self) -> bool:
        """Whether a dial is currently held."""
        with self._state_lock:
            return self._current is not None

    @property
    def has_reader(self) -> bool:
        """Whether the current dial has a reader started on it."""
        with self._state_lock:
            return self._current is not None and self._current.has_reader

    @property
    def ready(self) -> ReadyMessage | None:
        """The ``ReadyMessage`` the handshake received, or ``None`` if not open."""
        with self._state_lock:
            held = self._current
        return None if held is None else held.ready

    @property
    def endpoint(self) -> str:
        """The label of the display this is open to, for logs only.

        ``"not connected"`` is a placeholder for a closed connection, never a
        value to compare or parse.
        """
        with self._state_lock:
            held = self._current
        return "not connected" if held is None else held.endpoint

    def open(self, *, listening: bool = False) -> bool:
        """Dial the display and complete the handshake; whether this call dialed.

        The dial runs outside the state lock. With ``listening`` the new dial is
        born holding the listener's reader slot, so the listener never has to wait
        for it. Raises :class:`DisplayNotConnectedError` if the display cannot be
        reached or the handshake fails.
        """
        if self.is_open:
            return False
        fresh = DialGeneration(
            self._dialer.dial(self._connect_timeout),
            self.close_if_current,
            listening=listening,
        )
        with self._state_lock:
            if self._current is None:
                self._current = fresh
                return True
        fresh.shut()  # another caller dialed first; theirs stays
        return False

    def close(self) -> None:
        """Retire the current dial, if any."""
        with self._state_lock:
            held = self._current
            self._current = None
            if held is not None:
                held.mark_closed()
        if held is not None:
            held.shut()

    def close_if_current(self, generation: DialGeneration) -> bool:
        """Retire ``generation`` if it is still the current dial; whether it was.

        Atomic with the dial's publication: no interleaving closes a dial made
        after the check.
        """
        with self._state_lock:
            if self._current is not generation:
                return False
            self._current = None
            generation.mark_closed()
        generation.shut()
        return True

    def require(self) -> DialGeneration:
        """Return the current dial, or raise if the connection is not open."""
        with self._state_lock:
            held = self._current
        if held is None:
            msg = "Not connected — open() the display connection first"
            raise ConnectionClosedError(msg)
        return held
