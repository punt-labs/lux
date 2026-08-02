"""ClientSubmenu — one client's place in the Clients menu.

A client's submenu is its name over its own commands, with the Hub's ``Details``
command at the foot under a rule. Details sits in the same place for every
client, because it is the Hub's line rather than the client's, and a command that
moves is a command a user has to look for.

A leaf's id is the owning connection and the command joined into one wire id
(:class:`CallbackInvocation`), so a click round-trips to exactly the client that
registered it — or, for ``Details``, to the Hub itself.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.hub.menu_models import Menu, MenuAction, MenuSeparator
from punt_lux.domain.hub.session_callback import CallbackInvocation

if TYPE_CHECKING:
    from punt_lux.domain.hub.menu_models import MenuEntry
    from punt_lux.domain.hub.session_callback import SessionCallback
    from punt_lux.domain.ids import ConnectionId

__all__ = ["ClientSubmenu"]

# What the Hub's own per-client command reads as.
_DETAILS_LABEL = "Details"


@final
class ClientSubmenu:
    """One live client that registered commands, and the submenu it contributes."""

    _connection_id: ConnectionId
    _label: str
    _callbacks: tuple[SessionCallback, ...]
    __slots__ = ("_callbacks", "_connection_id", "_label")

    def __new__(
        cls,
        connection_id: ConnectionId,
        label: str,
        callbacks: tuple[SessionCallback, ...],
    ) -> Self:
        self = super().__new__(cls)
        self._connection_id = connection_id
        self._label = label
        self._callbacks = callbacks
        return self

    @property
    def label(self) -> str:
        """The name this client's submenu shows."""
        return self._label

    def menu(self) -> Menu:
        """This client's submenu: its commands in label order, then Details."""
        commands = sorted(
            (self._leaf(callback) for callback in self._callbacks),
            key=lambda action: action.label,
        )
        entries: list[MenuEntry] = [*commands, MenuSeparator(), self._details()]
        return Menu(label=self._label, items=entries)

    def _leaf(self, callback: SessionCallback) -> MenuAction:
        """One command, whose id round-trips a click back to this client."""
        menu_id = CallbackInvocation(self._connection_id, callback.id).menu_id
        return MenuAction(id=menu_id, label=callback.label)

    def _details(self) -> MenuAction:
        """The Hub's own command, which the Hub answers instead of routing."""
        return MenuAction(
            id=CallbackInvocation.details(self._connection_id).menu_id,
            label=_DETAILS_LABEL,
        )
