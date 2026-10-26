"""DisplayConnection -- which dial is current, and every write onto it.

The connection dials the display and says which :class:`DialGeneration` is current;
the generation owns its socket, its writes, its reader's bytes and the replies it
is owed, and reports its own breakage back through :meth:`retire`. A
state lock, distinct from every generation's socket lock, guards the current
generation and is held only for a field update, never across a dial, a write or a
close. Ending a generation is :meth:`close_if_current` for its reader and :meth:`retire`
for anyone else: each is a no-op unless that generation is still current, so a reader
or a waiter that outlived a redial can report its own dial's end without touching the
new one. Only a dial's reader, after it has read what the socket held, takes the ledger
of a dial the display ended or the Hub gave up on; the Hub's own end records its cause
first and takes the ledger only if that cause is the one that stands. The connection
also holds the suspects dials leave behind (the
:class:`~punt_lux.domain.hub.suspect_book.SuspectBook`) and the deaths not yet charged,
whose queue it hands out once.

The link's typed calls, the reader and the request waits are clients of it and
share no socket state of their own.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Literal, Self, final

from punt_lux.domain.hub.dial_generation import DialGeneration
from punt_lux.domain.hub.display_not_connected import DisplayNotConnectedError
from punt_lux.domain.hub.suspect_book import SuspectBook
from punt_lux.send_timeout import set_send_timeout

if TYPE_CHECKING:
    from collections.abc import Callable

    from punt_lux.domain.hub.connection_closed import RetireCause
    from punt_lux.domain.hub.death_queue import DeathQueue
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
    # The last dial to end, kept after it is gone: a caller that finds no dial learns
    # from it whether the display or the Hub ended it. None until the first
    # retirement, which is what "never opened" means.
    _last: DialGeneration | None
    # The scenes earlier dials left behind, and the deaths nobody has charged yet.
    _suspects: SuspectBook
    # Asked, when a dial is ended by someone who is not its reader, to see that its
    # reader settles it; supplied by whatever owns the readers.
    _settle_unread: Callable[[DialGeneration], None]
    _deaths_taken: bool
    __slots__ = (
        "_connect_timeout",
        "_current",
        "_deaths_taken",
        "_dialer",
        "_last",
        "_settle_unread",
        "_state_lock",
        "_suspects",
    )

    def __new__(
        cls,
        dialer: DisplayDialer,
        connect_timeout: float,
        *,
        settle_unread: Callable[[DialGeneration], None],
    ) -> Self:
        self = super().__new__(cls)
        self._dialer = dialer
        self._connect_timeout = connect_timeout
        self._state_lock = threading.Lock()
        self._current = None
        self._last = None
        self._suspects = SuspectBook()
        self._settle_unread = settle_unread
        self._deaths_taken = False
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
        if held is not None:
            self.retire(held, cause="hub")

    def close_if_current(
        self, generation: DialGeneration, *, cause: RetireCause
    ) -> bool:
        """Settle ``generation`` as its reader, if it is still the current dial.

        The reader's door, for a reader that has read the socket to the end it was
        going to read (a listener thread, an inline read, or whoever found a dial with
        no reader and read it for it). Everyone else ends a dial through
        :meth:`retire`. Atomic with the dial's publication: no interleaving closes a
        dial made after the check. ``cause`` is recorded unless someone already
        recorded one. Returns whether this call settled it.
        """
        return self._capture(generation, cause, by_reader=True)

    def retire(self, generation: DialGeneration, *, cause: RetireCause) -> bool:
        """End ``generation`` on behalf of a caller that is not its reader.

        Every end records its cause on the dial first. A display end or an
        unresponsive end is only recorded, first cause wins, and the dial's reader
        settles it after it has read everything the socket held: only then is the
        ledger complete (a dial with no reader is settled by the discoverer, through
        ``settle_unread``). The Hub's own end settles at once, but only if its cause is
        the one that stands: when a display end got there first the capture is left to
        the reader, and this returns ``False``. Returns whether this call ended the
        dial.
        """
        with self._state_lock:
            if self._current is not generation:
                return False
        if cause == "hub":
            generation.end("hub")  # atomic with the cause: first to record wins
            if self._capture(generation, "hub", by_reader=False):
                return True
            if generation.ended != "hub":
                self._settle_unread(generation)  # the display ended it: read it first
            return False
        won = generation.end(cause)
        self._settle_unread(generation)  # a dial with no reader has no one else
        return won

    def holds(self, generation: DialGeneration) -> bool:
        """Whether ``generation`` is the current dial."""
        with self._state_lock:
            return self._current is generation

    def take_deaths(self) -> DeathQueue:
        """Hand over the queue of deaths not yet charged, once: its holder charges.

        Raises ``ValueError`` on a second ask, so no second part of the Hub can take
        a death out from under the charger.
        """
        if self._deaths_taken:
            msg = "the display's deaths were already handed to a charger"
            raise ValueError(msg)
        self._deaths_taken = True
        return self._suspects.deaths

    def _capture(
        self, generation: DialGeneration, cause: RetireCause, *, by_reader: bool
    ) -> bool:
        """Take ``generation``'s ledger and make it not current; whether this did.

        The one place a ledger is taken. A caller that is not the dial's reader is
        refused a dial the display or the keepalive already ended: the reader has not
        read the socket to the end, and the ledger is not yet whole.
        """
        with self._state_lock:
            if self._current is not generation:
                return False
            if not by_reader and generation.ended in ("display", "unresponsive"):
                return False
            self._current = None
            self._last = generation
            self._settled(generation, cause)
        generation.shut()
        return True

    def _settled(self, generation: DialGeneration, cause: RetireCause) -> None:
        """Take a dial's ledger; keep its suspects or queue its death (state lock)."""
        self._suspects.settle(generation.mark_closed(cause), generation.endpoint)

    def _dial(self, reader: Literal["none", "listener"]) -> DialGeneration | None:
        """Dial and publish a generation with ``reader``; ``None`` if already open."""
        if self.is_open:
            return None
        dialed = self._dialed()
        set_send_timeout(dialed.sock)  # every dial path: a wedged peer ends a send
        fresh = DialGeneration(
            dialed,
            lambda generation, cause: self.retire(generation, cause=cause),
            reader=reader,
        )
        with self._state_lock:
            if self._current is None:
                self._current = fresh
                return fresh
        fresh.shut()  # another caller dialed first; theirs stays
        return None

    def _dialed(self) -> HandshakeResult:
        """Dial the display; a failure is the dialer's own."""
        return self._dialer.dial(self._connect_timeout)

    def require(self) -> DialGeneration:
        """Return the current dial, or raise the error that says why there is none.

        The error carries who ended the last dial: :class:`ConnectionClosedError`
        when the display did, :class:`UnresponsiveError` when the Hub gave up on its
        silence, :class:`HubRetiredError` when the Hub ended it by its own policy
        (the display is not at fault), and :class:`DisplayNotConnectedError` when no
        dial was ever made.
        """
        with self._state_lock:
            held = self._current
            last = self._last
        if held is not None:
            return held
        if last is None:
            msg = "Not connected -- open() the display connection first"
            raise DisplayNotConnectedError(msg)  # nothing was ever dialed
        raise last.closed_error()
