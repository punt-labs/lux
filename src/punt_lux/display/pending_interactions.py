"""PendingInteractions — hold display interactions across a brief Hub dropout.

When the display's connection to the Hub drops, the display keeps rendering but
has no one to forward a click to. Dropping those interactions is what made a
transient disconnect feel like "selection stopped working": the clicks fired
display-side and vanished. This buffer holds them so a reconnect within the bound
(the Hub's keepalive re-establishes the connection) delivers the clicks in order.

Each held interaction keeps the time it was first held, so the age bound is
re-checked every flush -- even one a stalled frame delays past the bound. An
interaction that ages out (or is pushed past the count cap) is returned for
compensation: an optimistic modal dismiss is reverted so the display reverts to
Hub truth. Delivery removes a delivered prefix and leaves the rest held, their
original ages intact, for the next frame.
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass
from typing import TYPE_CHECKING, Self, final

from punt_lux.connection_timing import CONNECTION_TIMING

if TYPE_CHECKING:
    from collections.abc import Iterable

    from punt_lux.protocol import RemoteEventHandlerInvocation

logger = logging.getLogger(__name__)

__all__ = ["DEFAULT_MAX_AGE", "DEFAULT_MAX_COUNT", "PendingInteractions"]

# Hold a click at least as long as the keepalive's worst-case reconnect (derived
# in connection_timing from the keepalive timing, so the two cannot drift apart)
# rather than compensating it away one tick before the reconnect that delivers it.
DEFAULT_MAX_AGE = CONNECTION_TIMING.interaction_max_age
# A cap on held interactions so a user clicking a disconnected display cannot grow
# the buffer without bound; the oldest are evicted (and compensated) first.
DEFAULT_MAX_COUNT = 128


@final
@dataclass(frozen=True, slots=True)
class _Held:
    """One buffered interaction and the monotonic time it was first held."""

    event: RemoteEventHandlerInvocation
    held_at: float


@final
class PendingInteractions:
    """A bounded FIFO of interactions awaiting delivery to the Hub.

    ``admit`` adds this frame's interactions; ``expire`` returns the ones that
    aged or overflowed past the bound (the caller compensates those); a delivery
    attempt reads ``pending_events`` and then ``discard_prefix`` removes the ones
    that landed, leaving the rest held -- with their original ages -- for the next
    frame. Ages are held per event, so a stalled frame cannot make an entry
    immortal: the very next ``expire`` re-checks it.
    """

    _events: deque[_Held]
    _max_age: float
    _max_count: int
    __slots__ = ("_events", "_max_age", "_max_count")

    def __new__(
        cls,
        max_age: float = DEFAULT_MAX_AGE,
        max_count: int = DEFAULT_MAX_COUNT,
    ) -> Self:
        self = super().__new__(cls)
        self._events = deque()
        self._max_age = max_age
        self._max_count = max_count
        return self

    @property
    def is_empty(self) -> bool:
        """Whether nothing is currently held."""
        return not self._events

    def admit(self, new: Iterable[RemoteEventHandlerInvocation], now: float) -> None:
        """Append this frame's interactions, each stamped with the time held."""
        self._events.extend(_Held(event, now) for event in new)

    def expire(self, now: float) -> list[RemoteEventHandlerInvocation]:
        """Remove and return interactions aged or overflowed past the bound.

        Checked every flush, so an entry a stalled frame carried past ``max_age``
        is evicted the next time this runs, not left to live forever. The returned
        events are undeliverable and the caller compensates them.
        """
        evicted = self._evict_aged(now)
        evicted.extend(self._evict_overflow())
        if evicted:
            logger.warning(
                "%d interaction(s) undeliverable past the %.1fs buffer: %s",
                len(evicted),
                self._max_age,
                [f"{ev.element_id}:{ev.event_kind}" for ev in evicted],
            )
        return evicted

    def pending_events(self) -> list[RemoteEventHandlerInvocation]:
        """Return the held interactions in order, for a delivery attempt."""
        return [pending.event for pending in self._events]

    def discard_prefix(self, count: int) -> None:
        """Drop the first ``count`` interactions -- the prefix a delivery landed."""
        for _ in range(count):
            self._events.popleft()

    def _evict_aged(self, now: float) -> list[RemoteEventHandlerInvocation]:
        """Remove and return interactions held past ``max_age`` (oldest first)."""
        evicted: list[RemoteEventHandlerInvocation] = []
        while self._events and now - self._events[0].held_at > self._max_age:
            evicted.append(self._events.popleft().event)
        return evicted

    def _evict_overflow(self) -> list[RemoteEventHandlerInvocation]:
        """Remove and return the oldest interactions beyond ``max_count``."""
        evicted: list[RemoteEventHandlerInvocation] = []
        while len(self._events) > self._max_count:
            evicted.append(self._events.popleft().event)
        return evicted
