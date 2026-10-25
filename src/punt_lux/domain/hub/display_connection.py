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
from typing import TYPE_CHECKING, Literal, Self, final

from punt_lux.domain.hub.connection_closed import (
    ConnectionClosedError,
    HubRetiredError,
)
from punt_lux.domain.hub.dial_generation import DialGeneration
from punt_lux.domain.hub.display_lost import DisplayLostError
from punt_lux.domain.hub.display_not_connected import DisplayNotConnectedError
from punt_lux.domain.hub.request_exchange import RequestExchange

if TYPE_CHECKING:
    from punt_lux.domain.hub.connection_closed import RetireCause
    from punt_lux.domain.hub.display_dialer import DisplayDialer
    from punt_lux.domain.hub.handshake_outcome import HandshakeResult
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
    # Who ended the last dial, and which dial it was, kept after it is gone: a caller
    # that finds no dial learns from them whether the display or the Hub ended it.
    # None until the first retirement, which is what "never opened" means.
    _last_ended: RetireCause | None
    _last: DialGeneration | None
    __slots__ = (
        "_connect_timeout",
        "_current",
        "_dialer",
        "_last",
        "_last_ended",
        "_state_lock",
    )

    def __new__(cls, dialer: DisplayDialer, connect_timeout: float) -> Self:
        self = super().__new__(cls)
        self._dialer = dialer
        self._connect_timeout = connect_timeout
        self._state_lock = threading.Lock()
        self._current = None
        self._last = None
        self._last_ended = None
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

    def open(self) -> None:
        """Dial the display and complete the handshake; a no-op if already open.

        The dial runs outside the state lock. Raises
        :class:`DisplayNotConnectedError` if the display cannot be reached or the
        handshake fails.
        """
        self._dial("none")

    def open_listening(self) -> DialGeneration | None:
        """Dial the display, the new dial born holding the listener's reader slot.

        Returns the dial this call made, or ``None`` if the connection was already
        open (no dial was made). The listener never has to wait for a dial born
        this way; the caller starts it on the generation returned, never on
        whatever is current by then.
        """
        return self._dial("listener")

    def close(self) -> None:
        """Retire the current dial, if any: the Hub's own deliberate close."""
        with self._state_lock:
            held = self._current
            self._current = None
            if held is not None:
                held.mark_closed("hub")
                self._last = held
                self._last_ended = "hub"
        if held is not None:
            held.shut()

    def close_if_current(
        self, generation: DialGeneration, *, cause: RetireCause
    ) -> bool:
        """Retire ``generation`` if it is still the current dial; whether it was.

        Atomic with the dial's publication: no interleaving closes a dial made
        after the check. ``cause`` says who ended it, for whoever finds it gone.
        """
        with self._state_lock:
            if self._current is not generation:
                return False
            self._current = None
            self._last = generation
            self._last_ended = cause
            generation.mark_closed(cause)
        generation.shut()
        return True

    def _dial(self, reader: Literal["none", "listener"]) -> DialGeneration | None:
        """Dial and publish a generation with ``reader``; ``None`` if already open."""
        if self.is_open:
            return None
        fresh = DialGeneration(
            self._dialed(),
            lambda generation, cause: self.close_if_current(generation, cause=cause),
            reader=reader,
        )
        with self._state_lock:
            if self._current is None:
                self._current = fresh
                return fresh
        fresh.shut()  # another caller dialed first; theirs stays
        return None

    def _dialed(self) -> HandshakeResult:
        """Dial the display; a failure after the display ended the last dial says so.

        The redial that finds nobody home must not erase who ended the dial before
        it: the error names that dial (:class:`DisplayLostError`), so the death it
        evidences is still charged to what was being sent.
        """
        try:
            return self._dialer.dial(self._connect_timeout)
        except DisplayNotConnectedError as exc:
            with self._state_lock:
                last, ended = self._last, self._last_ended
            if last is None or ended != "display":
                raise
            msg = f"{exc}; the display had closed the last connection"
            raise DisplayLostError(msg, RequestExchange.name(last)) from exc

    def require(self) -> DialGeneration:
        """Return the current dial, or raise the error that says why there is none.

        The error carries who ended the last dial: :class:`ConnectionClosedError`
        when the display did (it died, so a sender may blame what it was sending),
        :class:`HubRetiredError` when the Hub did (the display is not at fault), and
        :class:`DisplayNotConnectedError` when no dial was ever made.
        """
        with self._state_lock:
            held = self._current
            ended = self._last_ended
        if held is not None:
            return held
        if ended == "display":
            msg = "the display closed the connection"
            raise ConnectionClosedError(msg)
        if ended == "hub":
            msg = "the Hub retired the connection"
            raise HubRetiredError(msg)
        msg = "Not connected -- open() the display connection first"
        raise DisplayNotConnectedError(msg)  # nothing was ever dialed
