"""DialEnd -- how a dial's end stands: the cause recorded first, and the Hub's request.

A dial is ended by a party that knows why (the display, or a keepalive that gave up
on it), whose cause is *recorded*, and by the Hub, which only *asks*: a display that
died before the Hub asked is the display's end, and only the reader that has looked
at the socket can tell. The first cause recorded wins. :meth:`DialEnd.decide` fixes
the cause once the reader has looked. The object has no lock of its own: the
:class:`~punt_lux.domain.hub.reply_sink.ReplySink` that owns it guards every call.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from punt_lux.domain.hub.connection_closed import RetireCause

__all__ = ["DialEnd"]


@final
class DialEnd:
    """The first cause recorded for a dial's end, and whether the Hub asked."""

    _cause: RetireCause | None  # None until a cause is recorded or decided
    _hub_asked: bool
    __slots__ = ("_cause", "_hub_asked")

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._cause = None
        self._hub_asked = False
        return self

    @property
    # PY-TS-14 OK: None until a cause is recorded or decided: a dial may be open.
    def cause(self) -> RetireCause | None:
        """The first cause recorded or decided; ``None`` while there is none."""
        return self._cause

    @property
    # PY-TS-14 OK: None while nothing is ending the dial: no cause, no Hub request.
    def closing(self) -> RetireCause | None:
        """Who is ending the dial: the cause, else ``hub`` once the Hub asked."""
        return self._cause or ("hub" if self._hub_asked else None)

    def record(self, cause: RetireCause) -> bool:
        """Record ``cause`` unless one stands already; whether this call did."""
        if self._cause is not None:
            return False
        self._cause = cause
        return True

    def record_unless_closing(self, cause: RetireCause) -> bool:
        """Record ``cause`` unless one stands or the Hub has asked; whether it did.

        The writer's record: a write that fails after the Hub asked to end the dial
        records nothing, and the check and the record are one step.
        """
        if self._hub_asked:
            return False
        return self.record(cause)

    def ask_hub(self) -> bool:
        """Note that the Hub asked to end the dial; whether this call asked first."""
        if self._hub_asked:
            return False
        self._hub_asked = True
        return True

    def decide(self, *, saw_end: bool) -> RetireCause:
        """Fix the cause: the first recorded, else what the reader saw, else the Hub's.

        ``saw_end`` is the end of file (or reset) the reader's last look found: a
        display dead when the Hub looked is the display's end, never the Hub's.
        Raises ``ValueError`` for a dial nothing has ended or asked to end.
        """
        if self._cause is None:
            if saw_end:
                self._cause = "display"
            elif self._hub_asked:
                self._cause = "hub"
            else:
                msg = "a dial no one ended or asked to end has no cause to decide"
                raise ValueError(msg)
        return self._cause
