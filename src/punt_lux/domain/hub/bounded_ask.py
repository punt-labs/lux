"""BoundedAsk -- what an asker a held reader slot refused may do past the bound.

An end that finds the dial's reader slot held cannot settle the dial itself: the holder
is reading its socket, and settling it first would charge what the holder has yet to
read. It leaves a debt, which the holder honours when it lets go, and waits. A holder
that never lets go (a handler that blocks the listener thread, an inline read that
never returns) would leave the dial ended, current and unsettled for ever, and a dial
that is still current is one the Hub cannot replace. So the wait is bounded: after
:data:`SETTLE_BOUND` the asker records its own cause, first recorded wins, and settles
the dial without a drain. That is the one capture that does not belong to a holder,
and only a slot hands out the capability to make it.

A capture by the bound is undrained, so it may charge scenes whose acknowledgements
sit unread in the stalled holder's buffer; a Hub end captured this way charges nothing
and carries its scenes. Both are accepted.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from collections.abc import Callable

    from punt_lux.domain.hub.connection_closed import RetireCause
    from punt_lux.domain.hub.dial_generation import DialGeneration

__all__ = ["SETTLE_BOUND", "BoundedAsk"]

# How long an asker waits for a holder to settle: the listener's stop join.
SETTLE_BOUND = 2.0


@final
class BoundedAsk:
    """A refused asker's right to capture the dial, once the bound has passed."""

    _generation: DialGeneration
    _capture: Callable[[DialGeneration, RetireCause], bool]
    _bound: float
    __slots__ = ("_bound", "_capture", "_generation")

    def __new__(
        cls,
        generation: DialGeneration,
        capture: Callable[[DialGeneration, RetireCause], bool],
    ) -> Self:
        self = super().__new__(cls)
        self._generation = generation
        self._capture = capture
        self._bound = SETTLE_BOUND  # read now, so a test may shorten or lengthen it
        return self

    def settle_by_bound(self, cause: RetireCause) -> bool:
        """Wait for the holder to settle the dial; past the bound, settle it undrained.

        Returns whether this call captured the dial. ``cause`` is recorded first
        wins, and the cause that stands is the one captured.
        """
        generation = self._generation
        if generation.await_settled(self._bound):
            return False
        generation.end(cause)
        return self._capture(generation, generation.decide(saw_end=False))
