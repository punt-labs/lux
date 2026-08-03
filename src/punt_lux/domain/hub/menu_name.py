"""MenuName — the base a client is called and the ordinal telling it from its twins.

What the menu prints is one string, ``lux`` or ``lux (2)``, but it is made of two
things that behave differently. The base is what the client *is* called — the
repository it works in, or what it calls itself. The ordinal exists only to
separate clients that read the same way, and it is meaningful only while more
than one of them is there.

Holding the two apart is what lets the roster hand a base back to a survivor when
its holder goes. A roster that kept only the printed string would have to read a
number back out of a label it once wrote to know what ``lux (2)`` is a second
*of*; here the base was never thrown away, so falling back to it is
:attr:`plain`, not a parse.

The ordinal starts at one, and one prints as the bare base: the first client of a
name is not ``lux (1)``. That makes the plain name and the numbered names one
kind of value rather than two, so nothing has to case-split on whether a client
happens to be the first of its name.
"""

from __future__ import annotations

from itertools import count
from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from collections.abc import Container

__all__ = ["MenuName"]

# The ordinal the first client of a name holds, and the one that prints bare.
_FIRST = 1


@final
class MenuName:
    """One client's menu name: the base it reads as, and which of that name it is."""

    _base: str
    _ordinal: int
    __slots__ = ("_base", "_ordinal")

    def __new__(cls, base: str, ordinal: int = _FIRST) -> Self:
        self = super().__new__(cls)
        self._base = base
        self._ordinal = ordinal
        return self

    @classmethod
    def unheld(cls, base: str, held: Container[str]) -> Self:
        """Return the lowest name for *base* whose label nothing in *held* carries.

        The first client of a name takes the base itself; each one after it takes
        the lowest number still free, so a number freed by a departure is reused
        rather than skipped past.
        """
        return next(
            name for n in count(_FIRST) if (name := cls(base, n)).label not in held
        )

    @property
    def label(self) -> str:
        """What the menu prints — the base alone, or the base and its number."""
        if self._ordinal == _FIRST:
            return self._base
        return f"{self._base} ({self._ordinal})"

    @property
    def plain(self) -> Self:
        """This name with no number: what its holder is called once it is alone."""
        return type(self)(self._base)

    def __repr__(self) -> str:
        """Show both parts, since a label alone hides which base a name is one of."""
        return f"MenuName({self._base!r}, {self._ordinal!r})"
