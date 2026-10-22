"""ClientSubmenu — one client's place in the Clients menu.

A submenu is one group's name over its members' callbacks, then the Hub's own
``Details`` command, aimed at the senior member (never two identical Details).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.hub.menu_frames import MenuFrames
from punt_lux.domain.hub.menu_models import Menu, MenuAction, MenuSeparator
from punt_lux.domain.hub.session_callback import CallbackInvocation

if TYPE_CHECKING:
    from punt_lux.domain.hub.menu_models import MenuEntry
    from punt_lux.domain.hub.named_sessions import NamedGroup, NamedSession

__all__ = ["ClientSubmenu"]

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
        """This submenu: every member's commands in label order, then Details.

        A group with no commands -- a bare agent session -- shows just its
        Details, with no leading rule above nothing.
        """
        commands = sorted(self._leaves(), key=lambda action: action.label)
        rule: list[MenuEntry] = [MenuSeparator()] if commands else []
        return Menu(label=self._label, items=[*commands, *rule, self._details()])

    def _leaves(self) -> list[MenuAction]:
        """Every command a member registered, its frame scoped to the owner."""
        return [
            MenuAction(
                id=CallbackInvocation(member.connection_id, callback.id).menu_id,
                label=callback.label,
                frame_id=MenuFrames(member.connection_id).of(callback),
            )
            for member in self._members
            for callback in member.callbacks
        ]

    def _details(self) -> MenuAction:
        """The Hub's own command, aimed at the senior member, naming its frame."""
        senior = self._members[0]
        return MenuAction(
            id=CallbackInvocation.details(senior.connection_id).menu_id,
            label=_DETAILS_LABEL,
            frame_id=MenuFrames(senior.connection_id).details,
        )
