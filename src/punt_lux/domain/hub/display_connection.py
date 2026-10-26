"""DisplayConnection -- which dial is current, and every write onto it.

The connection dials the display and says which :class:`DialGeneration` is current,
together with the :class:`~punt_lux.domain.hub.reader_slot.ReaderSlot` that says who
reads it; the generation owns its socket, its writes, its reader's bytes and the replies
it is owed, and reports its own breakage back through :meth:`retire`. A state lock,
distinct from every generation's socket lock, guards the published dial and is held
only for a field update, never across a dial, a write or a close.

No one ends a dial by capturing it. An end *records* its cause (a display or
unresponsive end) or *requests* the Hub's (a Hub end records nothing, since the display
may have died already), and then asks for the dial to be settled: the holder of the
dial's reader slot, which has read what the socket held, drains it, fixes the cause and
takes its ledger. The one door to that capture is private to the connection and handed
to the slot alone, so a settle is the reader's and no flag can lend it to anyone else,
save the two undrained captures the design accepts: the bound's, by a refused asker
once :data:`~punt_lux.domain.hub.bounded_ask.SETTLE_BOUND` has passed, and
``Settler.end_stream``'s, for a stream that cannot be read past. Every capture is
guarded by "this dial is still current", so a reader or a waiter that outlived a redial
can settle its own dial without touching the new one. The connection also holds the
suspects dials leave behind (the
:class:`~punt_lux.domain.hub.suspect_book.SuspectBook`) and the deaths not yet charged,
whose queue it hands out once.

The link's typed calls, the reader and the request waits are clients of it and
share no socket state of their own.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Self, final

from punt_lux.domain.hub.dial_generation import DialGeneration
from punt_lux.domain.hub.display_not_connected import DisplayNotConnectedError
from punt_lux.domain.hub.reader_slot import ReaderSlot
from punt_lux.domain.hub.suspect_book import SuspectBook
from punt_lux.send_timeout import set_send_timeout

if TYPE_CHECKING:
    from collections.abc import Callable

    from punt_lux.domain.hub.connection_closed import RetireCause
    from punt_lux.domain.hub.death_queue import DeathQueue
    from punt_lux.domain.hub.display_dialer import DisplayDialer
    from punt_lux.protocol import ReadyMessage

__all__ = ["DisplayConnection"]


@dataclass(frozen=True, slots=True)
class _Published:
    """A dial and who reads it: made together, current together, gone together."""

    generation: DialGeneration
    slot: ReaderSlot


@final
class DisplayConnection:
    """The current dial to the display: dialed on open, retired on close."""

    _dialer: DisplayDialer
    _connect_timeout: float
    _state_lock: threading.Lock
    # None = not connected. The generation holds the socket, its endpoint and its
    # ready message; the slot says who reads it: one handshake's result, coming and
    # going together.
    _current: _Published | None
    # The last dial to end, kept after it is gone: a caller that finds no dial learns
    # from it whether the display or the Hub ended it. None until the first
    # retirement, which is what "never opened" means.
    _last: DialGeneration | None
    # The scenes earlier dials left behind, and the deaths nobody has charged yet.
    _suspects: SuspectBook
    # Asked, when a dial is ended by someone who may not settle it, to see that the
    # holder of its reader slot does; supplied by whatever owns the readers.
    _ask_settle: Callable[[DialGeneration, RetireCause], None]
    __slots__ = (
        "_ask_settle",
        "_connect_timeout",
        "_current",
        "_dialer",
        "_last",
        "_state_lock",
        "_suspects",
    )

    def __new__(
        cls,
        dialer: DisplayDialer,
        connect_timeout: float,
        *,
        ask_settle: Callable[[DialGeneration, RetireCause], None],
    ) -> Self:
        self = super().__new__(cls)
        self._dialer = dialer
        self._connect_timeout = connect_timeout
        self._state_lock = threading.Lock()
        self._current = None
        self._last = None
        self._suspects = SuspectBook()
        self._ask_settle = ask_settle
        return self

    @property
    def is_open(self) -> bool:
        """Whether a dial is currently held."""
        with self._state_lock:
            return self._current is not None

    @property
    def has_reader(self) -> bool:
        """Whether the current dial has a listener thread started on it."""
        with self._state_lock:
            return self._current is not None and self._current.slot.has_listener

    def reading(self, generation: DialGeneration) -> ReaderSlot | None:
        """Who reads ``generation``, if it is still the current dial; else ``None``.

        The slot is built with the dial and published with it, so it names the one
        reader a dial's socket may have: nobody, its listener thread, or one
        caller's inline wait. A dial that is no longer current has been settled and
        is read by no one, so it has no slot to lend. Returning the slot takes
        nothing: claiming or waiting on it is the caller's, never under the state
        lock.
        """
        with self._state_lock:
            published = self._current
        if published is not None and published.generation is generation:
            return published.slot
        return None

    def require_reading(self) -> tuple[DialGeneration, ReaderSlot]:
        """The current dial and its slot, taken in one look; raises if there is none.

        The error is the one :meth:`require` raises. One lock hold names both, so a
        redial cannot come between asking for the dial and asking who reads it.
        """
        with self._state_lock:
            published = self._current
            last = self._last
        if published is not None:
            return published.generation, published.slot
        raise self._why_none(last)

    @property
    def ready(self) -> ReadyMessage | None:
        """The ``ReadyMessage`` the handshake received, or ``None`` if not open."""
        with self._state_lock:
            held = self._current
        return None if held is None else held.generation.ready

    @property
    def endpoint(self) -> str:
        """The label of the display this is open to, for logs only.

        ``"not connected"`` is a placeholder for a closed connection, never a
        value to compare or parse.
        """
        with self._state_lock:
            held = self._current
        return "not connected" if held is None else held.generation.endpoint

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
            self.retire(held.generation, cause="hub")

    def retire(self, generation: DialGeneration, *, cause: RetireCause) -> bool:
        """End ``generation``, unless it is no longer current; whether this call did.

        Records the cause (first wins) for a display or unresponsive end, and only
        *requests* the Hub's, which records none. Either way the dial refuses writes
        and fails its waiters at once, and then the settle is asked for: it is the
        holder of the dial's reader slot that drains the socket, fixes the cause and
        takes the ledger, never this call. Returns whether this call recorded the end
        or made the request first.
        """
        with self._state_lock:
            if self._current is None or self._current.generation is not generation:
                return False
        won = generation.request_hub() if cause == "hub" else generation.end(cause)
        self._ask_settle(generation, cause)
        return won

    def _end_by_writer(self, generation: DialGeneration, cause: RetireCause) -> bool:
        """End ``generation`` for a failed write; whether the write's cause stands.

        The record refuses, in one step with its own check, when a cause stands or the
        Hub has asked; the settle is asked for in every case.
        """
        with self._state_lock:
            if self._current is None or self._current.generation is not generation:
                return False
        won = generation.end_by_writer(cause)
        self._ask_settle(generation, cause)
        return won

    def take_deaths(self) -> DeathQueue:
        """Hand over the queue of deaths not yet charged, once: its holder charges.

        Raises ``ValueError`` on a second ask, so no second part of the Hub can take
        a death out from under the charger.
        """
        return self._suspects.hand_over()

    def _capture(self, generation: DialGeneration, cause: RetireCause) -> bool:
        """Take ``generation``'s ledger and make it not current; whether this did.

        The one door a settle goes through, handed to the dial's reader slot and to
        nothing else. Atomic with the dial's publication: no interleaving closes a
        dial made after the check. ``cause`` is the one that stands, which the
        settler fixed before it came.
        """
        with self._state_lock:
            if self._current is None or self._current.generation is not generation:
                return False
            self._current = None
            self._last = generation
            self._suspects.settle(generation.mark_closed(cause), generation.endpoint)
        generation.shut()
        return True

    def _dial(self, reader: Literal["none", "listener"]) -> DialGeneration | None:
        """Dial and publish a generation with ``reader``; ``None`` if already open."""
        if self.is_open:
            return None
        dialed = self._dialer.dial(self._connect_timeout)  # a failure is the dialer's
        set_send_timeout(dialed.sock)  # every dial path: a wedged peer ends a send
        fresh = DialGeneration(
            dialed,
            lambda generation, cause: self.retire(generation, cause=cause),
            self._end_by_writer,
        )
        # Born holding the listener slot when asked: nobody else has seen this dial
        # yet, so no inline read can be in flight when the listener claims it.
        slot = ReaderSlot(reader, fresh, self._capture)
        with self._state_lock:
            if self._current is None:
                self._current = _Published(fresh, slot)
                return fresh
        fresh.shut()  # another caller dialed first; theirs stays
        return None

    def require(self) -> DialGeneration:
        """Return the current dial, or raise the error that says why there is none.

        The error carries who ended the last dial: :class:`ConnectionClosedError`
        when the display did, :class:`UnresponsiveError` when the Hub gave up on its
        silence, :class:`HubRetiredError` when the Hub ended it by its own policy
        (the display is not at fault), and :class:`DisplayNotConnectedError` when no
        dial was ever made.
        """
        return self.require_reading()[0]

    @staticmethod
    def _why_none(last: DialGeneration | None) -> Exception:
        """The error that says there is no current dial, and why."""
        if last is None:
            msg = "Not connected -- open() the display connection first"
            return DisplayNotConnectedError(msg)  # nothing was ever dialed
        return last.closed_error()
