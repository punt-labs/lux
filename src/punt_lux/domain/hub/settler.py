"""Settler -- the holder's right to settle a dial: drain it, fix its cause, capture it.

Only the holder of a dial's :class:`~punt_lux.domain.hub.reader_slot.ReaderSlot` (its
listener thread, an inline reader, or a releaser taking over) is handed a settler, and
only the slot makes one. Nothing else in the Hub can capture a dial, so a dial is
captured only after the party that reads its socket has read it, except by the two
undrained captures the design accepts: the bound's, which a refused asker makes once
:data:`~punt_lux.domain.hub.bounded_ask.SETTLE_BOUND` has passed, and
:meth:`Settler.end_stream`'s, for a stream that cannot be read past.

Settling is two steps. The drain reads the socket to the point where it would block
and notes whether the stream's end came. The decision then fixes the cause by the
dial's own first-wins record: the end seen is the display's, else a Hub request is the
Hub's, else the recorded cause stands. A cause recorded after the drain began (a write
failed, or the keepalive gave up, while it ran) means the drain was not complete, so
the settler drains once more before it captures; after the record is fixed nothing can
change the cause, so that second drain is the last.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.hub.dial_drain import DialDrain

if TYPE_CHECKING:
    from collections.abc import Callable

    from punt_lux.domain.hub.connection_closed import RetireCause
    from punt_lux.domain.hub.dial_generation import DialGeneration
    from punt_lux.protocol import Message

__all__ = ["Settler"]


@final
class Settler:
    """Settles one dial, for whoever holds the dial's reader slot."""

    _generation: DialGeneration
    _route: Callable[[DialGeneration, Message], None]
    _capture: Callable[[DialGeneration, RetireCause], bool]
    __slots__ = ("_capture", "_generation", "_route")

    def __new__(
        cls,
        generation: DialGeneration,
        route: Callable[[DialGeneration, Message], None],
        capture: Callable[[DialGeneration, RetireCause], bool],
    ) -> Self:
        self = super().__new__(cls)
        self._generation = generation
        self._route = route
        self._capture = capture
        return self

    def settle(self) -> bool:
        """Drain the dial, fix its cause, capture it; whether this call captured it.

        A no-op once the dial is not current. Raises ``ValueError`` for a dial that
        nothing has ended or asked to end.
        """
        generation = self._generation
        if generation.is_settled:
            return False  # captured already (by the bound): nothing is read or routed
        recorded_before = generation.ended
        saw_end = DialDrain(self._route).run(generation)
        cause = generation.decide(saw_end=saw_end)
        # A display or unresponsive end that nothing had recorded when the drain began
        # and the drain did not find itself was recorded under it: look once more.
        if recorded_before is None and not saw_end and cause != "hub":
            DialDrain(self._route).run(generation)
        return self._capture(generation, cause)

    def end_stream(self, cause: RetireCause) -> bool:
        """End a dial whose stream cannot be trusted, undrained; whether ``cause`` won.

        The cause is recorded first and the ledger is taken without a drain, because
        the stream cannot be read past: what sits behind a frame that did not decode
        is unread. An end another recorded first is the one that stands.
        """
        generation = self._generation
        won = generation.end(cause)
        self._capture(generation, cause)
        return won
