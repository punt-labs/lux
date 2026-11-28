"""One pending call, and the listen session it was sent to.

An entry owns its own outcome: it is concluded once, under the call table's lock,
and its waiter is woken afterwards, outside that lock.
"""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from collections.abc import Callable

    from punt_lux.hub.call_outcomes import CallOutcome

__all__ = ["CallEntry", "SessionTicket"]


@final
class SessionTicket:
    """One listen session, as the call table knows it; compared by identity."""

    __slots__ = ("_ended", "_number")

    _ended: bool
    _number: int

    def __new__(cls, number: int) -> Self:
        self = super().__new__(cls)
        self._number = number
        self._ended = False
        return self

    def end(self) -> None:
        """Mark the session ended; the call table's lock is held."""
        self._ended = True

    @property
    def ended(self) -> bool:
        """Whether the session has ended, so no request can reach it."""
        return self._ended

    def __repr__(self) -> str:
        return f"SessionTicket({self._number})"


@final
class CallEntry:
    """One pending call: where it went, what wakes its waiter, how it ended."""

    __slots__ = ("_clock", "_deadline", "_event", "_outcome", "_ticket")

    _clock: Callable[[], float]
    _deadline: float
    _event: threading.Event
    _outcome: CallOutcome | None
    _ticket: SessionTicket

    def __new__(
        cls,
        ticket: SessionTicket,
        deadline_s: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> Self:
        self = super().__new__(cls)
        self._ticket = ticket
        self._clock = clock
        self._deadline = clock() + deadline_s
        self._event = threading.Event()
        self._outcome = None
        return self

    def was_sent_to(self, ticket: SessionTicket) -> bool:
        """Whether this call went to ``ticket``'s session."""
        return self._ticket is ticket

    def conclude(self, outcome: CallOutcome) -> None:
        """Record the one outcome; the caller holds the table's lock."""
        self._outcome = outcome

    @property
    def outcome(self) -> CallOutcome | None:
        """The recorded outcome, or ``None`` while the call is pending."""
        return self._outcome

    @property
    def expired(self) -> bool:
        """Whether the deadline, measured from the send, has passed."""
        return self._clock() >= self._deadline

    def wake(self) -> None:
        """Release the waiter; called after the table's lock is dropped."""
        self._event.set()

    def wait_until_deadline(self) -> None:
        """Block until woken, or until the deadline measured from the send."""
        self._event.wait(max(0.0, self._deadline - self._clock()))
