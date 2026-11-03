"""MemberEntries — the menu entries one connection contributes to its submenu.

A connection that registered commands contributes one entry per command. One
that registered none -- the agent session -- contributes a single entry naming
itself, which the Hub answers by showing that connection's state. Either way an
entry names the frame it opens, so the Display can reopen it once the user has
closed it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.hub.menu_frames import MenuFrames
from punt_lux.domain.hub.menu_models import MenuAction
from punt_lux.domain.hub.session_callback import CallbackInvocation

if TYPE_CHECKING:
    from punt_lux.domain.hub.named_sessions import NamedSession

__all__ = ["MemberEntries"]


@final
class MemberEntries:
    """The entries one named connection adds to the submenu it sits in."""

    _member: NamedSession
    __slots__ = ("_member",)

    def __new__(cls, member: NamedSession) -> Self:
        self = super().__new__(cls)
        self._member = member
        return self

    def actions(self) -> list[MenuAction]:
        """Its commands, or one entry for the connection itself when it has none."""
        member = self._member
        frames = MenuFrames(member.connection_id)
        if not member.callbacks:
            return [
                MenuAction(
                    id=CallbackInvocation.details(member.connection_id).menu_id,
                    label=member.program,
                    frame_id=frames.details,
                )
            ]
        return [
            MenuAction(
                id=CallbackInvocation(member.connection_id, callback.id).menu_id,
                label=callback.label,
                frame_id=frames.of(callback),
            )
            for callback in member.callbacks
        ]
