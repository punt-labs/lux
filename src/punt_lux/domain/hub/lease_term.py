"""How long a session's lease runs — a state, never a sentinel.

A lease either lapses after some length of time or never lapses at all. Those
are two states, not one number with a magic value in it: luxd's own built-ins
hold a lease that never ends, and writing that as ``inf`` puts a float in the
model that no JSON can carry — ``json`` writes it as ``Infinity``, which is not
JSON, and pydantic writes it as ``null`` and then refuses to read it back. Any
client reading the session roster over HTTP loses the whole response because one
daemon is permanent.

So the two states are two types, discriminated on ``kind``. Each renders itself,
so nothing downstream asks "is this one infinite?" before deciding what to
print, and :class:`LeaseTerms` is the one place a length becomes a state.

The arithmetic that decides whether a lease has lapsed stays on
:class:`~punt_lux.domain.hub.session_lease.SessionLease`, where ``inf`` is a
perfectly good number to compare against. This is the shape that leaves the Hub.
"""

from __future__ import annotations

from math import isinf
from typing import Annotated, Literal, final

from pydantic import BaseModel, ConfigDict, Field

from punt_lux.domain.span import Span

__all__ = ["ExpiringLease", "LeaseTerm", "LeaseTerms", "PermanentLease"]


class PermanentLease(BaseModel):
    """A lease that never lapses — luxd's own built-ins hold one."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["permanent"] = "permanent"

    def rendered(self) -> str:
        """Render as the line a person reads."""
        return "permanent"


class ExpiringLease(BaseModel):
    """A lease that lapses unless the session makes contact within its length."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["expiring"] = "expiring"
    seconds: float = Field(gt=0)  # a lease of no length would lapse on arrival

    def rendered(self) -> str:
        """Render as the line a person reads."""
        return Span.of(self.seconds).rendered()


# A lease is one state or the other, discriminated on ``kind`` so it round-trips
# through JSON without either side guessing which it is.
LeaseTerm = Annotated[PermanentLease | ExpiringLease, Field(discriminator="kind")]


@final
class LeaseTerms:
    """The choice between the two states, made once, from a length in seconds."""

    __slots__ = ()

    @classmethod
    def of(cls, seconds: float) -> LeaseTerm:
        """Return the term a lease of *seconds* runs for.

        The one place ``inf`` stops being a number and becomes a state: the
        arithmetic that owns the number keeps it, and everything that reports a
        lease gets one of the two states instead.
        """
        return PermanentLease() if isinf(seconds) else ExpiringLease(seconds=seconds)
