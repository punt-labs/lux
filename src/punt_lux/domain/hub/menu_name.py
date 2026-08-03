"""What a client's menu name is, and how a set of them stays readable.

What the menu prints is one string, ``lux`` or ``lux (2)``, but it is made of two
things that behave differently. The base is what the client *is* called — the
repository it works in, or what it calls itself. The ordinal exists only to
separate clients that read the same way, and it is meaningful only while more
than one of them is there. :class:`MenuName` is that pair; :class:`MenuNames` is
every name held at once, and the discipline that keeps a number from outliving
what it distinguished.

Holding the base and the ordinal apart is what lets a freed base go back to a
survivor. A collection that kept only the printed string would have to read a
number back out of a label it once wrote to know what ``lux (2)`` is a second
*of*; here the base was never thrown away, so falling back to it is
:attr:`~MenuName.plain`, not a parse.

The ordinal starts at one, and one prints as the bare base: the first client of a
name is not ``lux (1)``. That makes the plain name and the numbered names one
kind of value rather than two, so nothing has to case-split on whether a client
happens to be the first of its name.

Nothing here knows what a holder is beyond something to key names by. Who is
still connected, and when a holder has gone, belong to
:class:`~punt_lux.domain.hub.client_roster.ClientRoster` and the registry above
it — this only keeps the names it is told to keep.
"""

from __future__ import annotations

from itertools import count
from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from collections.abc import Container, Iterable

    from punt_lux.domain.ids import ConnectionId

__all__ = ["MenuName", "MenuNames"]

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


@final
class MenuNames:
    """The names held right now, with no holder numbered against a free base.

    That is the invariant every operation here leaves standing: if anybody is
    ``lux (2)``, somebody is ``lux``. :meth:`take` keeps it by handing out the
    lowest free name, and :meth:`drop` restores it by giving a base a departure
    freed to the senior holder still numbered against it.

    Senior means the one that took its name first — the order names were assigned
    is the order this walks — which is the same rule that gives the plain name to
    the first of several holders arriving together, and is state rather than a
    number read back out of a label.

    A departure moves at most one name. With ``lux``, ``lux (2)`` and ``lux (3)``
    held and ``lux`` dropped, ``lux (2)`` becomes ``lux`` and ``lux (3)`` stays as
    it is: a number tells two holders apart, and closing the gap would rename a
    second entry to say nothing new.
    """

    _names: dict[ConnectionId, MenuName]
    __slots__ = ("_names",)

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._names = {}
        return self

    def take(self, holder: ConnectionId, base: str) -> None:
        """Give *holder* the lowest free name for *base*, unless it holds one already.

        A holder's name is its own for as long as it keeps it, so this never
        renames anybody: taking is the one operation that adds.
        """
        if holder not in self._names:
            self._names[holder] = MenuName.unheld(base, self._labels())

    def drop(self, holders: Iterable[ConnectionId]) -> None:
        """Take back what *holders* held, and hand any freed base on.

        A holder that held no name is no error — the caller may be removing
        something that was never named.
        """
        for holder in holders:
            self._names.pop(holder, None)
        self._reclaim_freed_bases()

    def labels(self) -> dict[ConnectionId, str]:
        """What each holder is called, as the last take or drop left it."""
        return {holder: name.label for holder, name in self._names.items()}

    def _reclaim_freed_bases(self) -> None:
        """Give each base nobody holds plainly to its senior numbered holder.

        The running set of held labels is what keeps the second holder of a base
        from following the first, and what makes a holder already holding its
        plain name stay put — so there is no case here for whether a name is
        numbered.
        """
        held = self._labels()
        promoted: dict[ConnectionId, MenuName] = {}
        for holder, name in self._names.items():
            if name.plain.label not in held:
                held.add(name.plain.label)
                promoted[holder] = name.plain
        self._names.update(promoted)

    def _labels(self) -> set[str]:
        """Every label held right now — what a new or falling-back name must miss."""
        return {name.label for name in self._names.values()}
