"""ClientSubmenu — one client's place in the Clients menu.

A submenu is one group's name over its members' callbacks, plus one entry for
each member that registered none, which the Hub answers itself.
"""

from __future__ import annotations

from itertools import chain
from operator import attrgetter
from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.hub.member_entries import MemberEntries
from punt_lux.domain.hub.menu_models import Menu

if TYPE_CHECKING:
    from punt_lux.domain.hub.menu_models import MenuEntry
    from punt_lux.domain.hub.named_sessions import NamedSession

__all__ = ["ClientSubmenu"]


@final
class ClientSubmenu:
    """One submenu: a group's name over what its members contribute."""

    _label: str
    _members: tuple[NamedSession, ...]
    __slots__ = ("_label", "_members")

    def __new__(cls, label: str, members: tuple[NamedSession, ...]) -> Self:
        self = super().__new__(cls)
        self._label = label
        self._members = members
        return self

    @property
    def label(self) -> str:
        """The name this submenu shows."""
        return self._label

    def menu(self) -> Menu:
        """This submenu: every member's entries in label order."""
        return Menu(label=self._label, items=self._ordered())

    def _ordered(self) -> list[MenuEntry]:
        """What the members contribute, by label."""
        actions = chain.from_iterable(MemberEntries(m).actions() for m in self._members)
        return sorted(actions, key=attrgetter("label"))
