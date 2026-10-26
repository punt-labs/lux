"""DisplayConnection -- which dial is current, and every write onto it.

The connection dials the display and says which :class:`DialGeneration` is current;
the generation owns its socket, its writes, its reader's bytes and the replies it
is owed, and reports its own breakage back through :meth:`retire`. A
state lock, distinct from every generation's socket lock, guards the current
generation and is held only for a field update, never across a dial, a write or a
close. Ending a generation is :meth:`close_if_current` for its reader and :meth:`retire`
for anyone else: each is a no-op unless that generation is still current, so a reader
or a waiter that outlived a redial can report its own dial's end without touching the
new one. The connection also holds the suspects dials leave behind (the
:class:`~punt_lux.domain.hub.suspect_book.SuspectBook`) and the deaths not yet charged.

The link's typed calls, the reader and the request waits are clients of it and
share no socket state of their own.
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from typing import TYPE_CHECKING, Literal, Self, final

from punt_lux.domain.hub.dial_generation import DialGeneration
from punt_lux.domain.hub.display_not_connected import DisplayNotConnectedError
from punt_lux.domain.hub.suspect_book import SuspectBook
from punt_lux.send_timeout import set_send_timeout

if TYPE_CHECKING:
    from collections.abc import Callable

    from punt_lux.domain.hub.connection_closed import RetireCause
    from punt_lux.domain.hub.dial_death import DialDeath
    from punt_lux.domain.hub.display_dialer import DisplayDialer
    from punt_lux.domain.hub.handshake_outcome import HandshakeResult
    from punt_lux.protocol import ReadyMessage

logger = logging.getLogger(__name__)

__all__ = ["DisplayConnection"]

# Deaths a replicator has not yet charged. The queue holds one per dial and is never
# trimmed: a dropped death is a scene never charged. Past this many it says so.
_PENDING_DEATHS_WARNING = 64


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
    # Display-ended dials whose ledger nobody has charged yet, oldest first.
    _deaths: deque[DialDeath]
    # The scenes earlier dials left behind that the display may still hold.
    _suspects: SuspectBook
    # Asked, when a dial is ended by someone who is not its reader, to see that its
    # reader settles it; set by whatever owns the readers.
    _settle_unread: Callable[[DialGeneration], None]
    __slots__ = (
        "_connect_timeout",
        "_current",
        "_deaths",
        "_dialer",
        "_last",
        "_settle_unread",
        "_state_lock",
        "_suspects",
    )

    def __new__(cls, dialer: DisplayDialer, connect_timeout: float) -> Self:
        self = super().__new__(cls)
        self._dialer = dialer
        self._connect_timeout = connect_timeout
        self._state_lock = threading.Lock()
        self._current = None
        self._last = None
        self._deaths = deque()
        self._suspects = SuspectBook()
        self._settle_unread = lambda _generation: None
        return self

    def settle_unread_with(self, settle: Callable[[DialGeneration], None]) -> None:
        """Say who settles a dial that someone other than its reader ended."""
        self._settle_unread = settle

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
                self._settled(held, "hub")  # the Hub's own close owes no one a death
                self._last = held
        if held is not None:
            held.shut()

    def close_if_current(
        self, generation: DialGeneration, *, cause: RetireCause
    ) -> bool:
        """Settle ``generation`` if it is still the current dial; whether it was.

        The end of a dial whose reader is the caller, or of one the Hub ends outright:
        the dial's ledger is captured here, so a display-ended dial must have been read
        to the end first (:meth:`retire` is the door for everyone else). Atomic with
        the dial's publication: no interleaving closes a dial made after the check.
        ``cause`` is recorded unless someone already recorded one.
        """
        with self._state_lock:
            if self._current is not generation:
                return False
            self._current = None
            self._last = generation
            self._settled(generation, cause)
        generation.shut()
        return True

    def retire(self, generation: DialGeneration, *, cause: RetireCause) -> bool:
        """End ``generation`` on behalf of a caller that is not its reader.

        The Hub's own end settles at once. A display end or an unresponsive end is
        only recorded, first cause wins, and the dial's reader settles it after it has
        read everything the socket held: only then is the ledger complete. A Hub end
        arriving after one of those is dropped, for the same reason. Returns whether
        this call ended the dial.
        """
        with self._state_lock:
            if self._current is not generation:
                return False
        if cause == "hub":
            if generation.ended in ("display", "unresponsive"):
                return False  # the reader settles it, ledger and all
            return self.close_if_current(generation, cause="hub")
        won = generation.end(cause)
        self._settle_unread(generation)  # a dial with no reader has no one else
        return won

    def take_death(self) -> DialDeath | None:
        """Hand over the oldest display-ended dial not yet charged; each once."""
        with self._state_lock:
            return self._deaths.popleft() if self._deaths else None

    def _settled(self, generation: DialGeneration, cause: RetireCause) -> None:
        """Take a dial's ledger; keep its suspects or queue its death (state lock)."""
        settlement = generation.mark_closed(cause)
        death = self._suspects.settle(settlement, generation.endpoint)
        if death is not None:
            self._record(death)

    def _record(self, death: DialDeath) -> None:
        """Queue a death for the replicator: never dropped, but never unnoticed."""
        self._deaths.append(death)
        if len(self._deaths) > _PENDING_DEATHS_WARNING:
            logger.warning(
                "%d display deaths wait to be charged: is the replicator running?",
                len(self._deaths),
            )

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
        when the display did (it died, so a sender may blame what it was sending),
        :class:`HubRetiredError` when the Hub did (the display is not at fault), and
        :class:`DisplayNotConnectedError` when no dial was ever made.
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
