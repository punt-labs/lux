"""ClientSubmenu — one client's place in the Clients menu.

A submenu is one group's name over the callbacks its members registered, with
the Hub's ``Details`` command at the foot under a rule. A group is usually one
session, but two applets in one session share a name and share one submenu, so
the entries can come from several connections — every callback carries the
connection it belongs to, and a click routes to whichever applet registered
that callback.

The Details entry sits in the same place for every submenu, because it is the
Hub's line rather than the client's, and a command that moves is a command a
user has to look for. When several sessions share the submenu, Details points
at the senior — the first-registered member — because two identical Details
entries would ask a user to guess.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.hub.menu_models import Menu, MenuAction, MenuSeparator
from punt_lux.domain.hub.session_callback import CallbackInvocation

if TYPE_CHECKING:
    from punt_lux.domain.hub.menu_models import MenuEntry
    from punt_lux.domain.hub.named_sessions import NamedGroup, NamedSession

__all__ = ["ClientSubmenu"]

# What the Hub's own per-client command reads as.
_DETAILS_LABEL = "Details"


@final
class ClientSubmenu:
    """One submenu: a group's name over its members' commands, then Details."""

    _label: str
    _members: tuple[NamedSession, ...]
    __slots__ = ("_label", "_members")

    def __new__(cls, label: str, members: tuple[NamedSession, ...]) -> Self:
        self = super().__new__(cls)
        self._label = label
        self._members = members
        return self

    @classmethod
    def of(cls, group: NamedGroup) -> Self:
        """Build the submenu one :class:`NamedGroup` contributes."""
        return cls(group.name, group.members)

    @property
    def label(self) -> str:
        """The name this submenu shows."""
        return self._label

    def menu(self) -> Menu:
        """This submenu: every member's commands in label order, then Details."""
        commands = sorted(self._leaves(), key=lambda action: action.label)
        entries: list[MenuEntry] = [*commands, MenuSeparator(), self._details()]
        return Menu(label=self._label, items=entries)

    def _leaves(self) -> list[MenuAction]:
        """Every command any member of this group registered."""
        return [
            MenuAction(
                id=CallbackInvocation(member.connection_id, callback.id).menu_id,
                label=callback.label,
                frame_id=callback.frame_id,
            )
            for member in self._members
            for callback in member.callbacks
        ]

    def _details(self) -> MenuAction:
        """The Hub's own command, aimed at the senior member of this group."""
        senior = self._members[0]
        return MenuAction(
            id=CallbackInvocation.details(senior.connection_id).menu_id,
            label=_DETAILS_LABEL,
        )
