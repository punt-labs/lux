"""PendingInteractions — hold display interactions across a brief Hub dropout.

When the display's connection to the Hub drops, the display keeps rendering but
has no one to forward a click to. Dropping those interactions is what made a
transient disconnect feel like "selection stopped working": the clicks fired
display-side and vanished. This buffer holds them for a short bound so a
reconnect within it (the Hub's keepalive re-establishes the connection in about
one interval) delivers the clicks instead of losing them.

The bound is deliberately short. An interaction still undelivered past it is
treated as genuinely lost and returned to the caller for compensation — an
optimistic modal dismiss is reverted so the display reverts to Hub truth rather
than silently diverging. A count cap bounds memory if the user keeps clicking a
disconnected display.
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass
from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from collections.abc import Iterable

    from punt_lux.protocol import RemoteEventHandlerInvocation

logger = logging.getLogger(__name__)

__all__ = ["DEFAULT_MAX_AGE", "DEFAULT_MAX_COUNT", "PendingInteractions"]

# Long enough for the Hub's connection keepalive to notice the drop and reconnect
# (about one keepalive interval plus the reconnect), short enough that a genuinely
# gone display compensates its optimistic modal dismisses promptly.
DEFAULT_MAX_AGE = 3.0
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
    """A short bounded FIFO of interactions awaiting the Hub connection.

    ``hold`` accumulates interactions while no client is connected and returns
    the ones that aged or overflowed past the bound (the caller compensates
    those). ``drain_to`` empties the buffer ahead of freshly-queued events when a
    client is back, so a reconnect delivers the held clicks in their original
    order before the new ones.
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

    def hold(
        self, new: Iterable[RemoteEventHandlerInvocation], now: float
    ) -> list[RemoteEventHandlerInvocation]:
        """Buffer ``new`` interactions; return those aged or overflowed past bound.

        The returned events are undeliverable — held longer than ``max_age`` or
        pushed out beyond ``max_count`` — and the caller compensates them. The
        rest stay held for the next flush, where a reconnect can deliver them.
        """
        self._events.extend(_Held(event, now) for event in new)
        evicted = self._evict_aged(now)
        evicted.extend(self._evict_overflow())
        if evicted:
            logger.warning(
                "no display client connected; %d interaction(s) undeliverable past "
                "the %.1fs buffer: %s",
                len(evicted),
                self._max_age,
                [f"{ev.element_id}:{ev.event_kind}" for ev in evicted],
            )
        return evicted

    def drain_to(
        self, new: Iterable[RemoteEventHandlerInvocation]
    ) -> list[RemoteEventHandlerInvocation]:
        """Empty the buffer, then append ``new`` -- held clicks deliver first."""
        held = [pending.event for pending in self._events]
        self._events.clear()
        held.extend(new)
        return held

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
