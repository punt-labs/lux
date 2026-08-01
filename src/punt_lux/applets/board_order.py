"""BoardOrder — where a load sits in the order loads began.

Two loads can be in flight at once: the warm-up on one worker thread and an early
click on another, which is the case the warm-up exists for. Both end in a store,
so the applet needs a rule for which of two boards it keeps, and the rule is the
order the loads *began* in.

Began, not returned. A board is as old as the issues it shows, and which issues a
query will return is settled when it starts, not when it comes back. A warm-up
that begins before a click read the older issues however late its board arrives;
a click that begins after it read newer ones even if it returns first. Numbering
boards as they arrived would say the opposite in exactly that interleaving, and
keep the staler board on screen until somebody clicked again.

A place is a number rather than a clock reading, because all the rule needs is
which of two loads began first, and a counter answers that at every clock
resolution — including two loads that begin inside the same tick of one.
"""

from __future__ import annotations

from itertools import count
from typing import Self, final

__all__ = ["BoardOrder"]

# The order loads begin in. Taking a place is one step of one counter, so the two
# loading threads take theirs without a lock between them.
_LOADS = count()

# Where a state holding no board sits: before every load there has been or will
# be, so it is older than anything it might displace. Loads are numbered from
# zero as they begin.
_BEFORE_ANY_LOAD = -1


@final
class BoardOrder:
    """A load's place in the order loads began: what decides between two boards."""

    _place: int
    __slots__ = ("_place",)

    def __new__(cls, place: int) -> Self:
        self = super().__new__(cls)
        self._place = place
        return self

    @classmethod
    def beginning(cls) -> Self:
        """The place of a load that starts now — taken before its query runs."""
        return cls(next(_LOADS))

    @classmethod
    def before_any_load(cls) -> Self:
        """The place of a state holding no board: earlier than every load."""
        return cls(_BEFORE_ANY_LOAD)

    def after(self, other: BoardOrder) -> bool:
        """Whether the load holding this place began after the one holding *other*."""
        return self._place > other._place
