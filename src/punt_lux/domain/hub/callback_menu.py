"""Build the session-then-callback menu from the live Hub sessions.

The menu nests one way and one way only: one submenu per live session that has
registered a callback, labeled with that session's name, with its callbacks as the
leaves under it. This holds whatever the count — a session with one callback is a
single-leaf submenu, a session with several is a submenu with several leaves — so
there is no case logic and no count threshold that switches the shape. Two sessions
are never merged: each is its own submenu.

The label is the identity's name and nothing else. A client is what it calls
itself, not where it happens to sit, and a session that needs its repository read
out loud puts the repository in its name — which is what an applet does
(``lux · <repository> · #<process>``). Appending the path here as well would
duplicate that for a session and hang location noise off an app that has one name
and one meaning wherever it runs.

A leaf's id is the owning session and the callback joined into one wire id
(:class:`CallbackInvocation`), so a click on the leaf round-trips to exactly the
session that registered it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.hub.menu_models import Menu, MenuAction
from punt_lux.domain.hub.session_callback import CallbackInvocation

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

    from punt_lux.domain.hub.callback_ports import LiveSessions
    from punt_lux.domain.hub.client_identity import ClientIdentity
    from punt_lux.domain.hub.client_session import ClientSession
    from punt_lux.domain.hub.session_callback import SessionCallback
    from punt_lux.domain.ids import ConnectionId

__all__ = ["CallbackMenu", "CallbackMenuReplica"]

# One qualifying session's parts for a submenu: its connection, its declared
# identity, and the callbacks it registered — narrowed past the None-identity case.
_Qualifying = tuple["ConnectionId", "ClientIdentity", "tuple[SessionCallback, ...]"]


@final
class CallbackMenu:
    """Compose the uniform session-then-callback menu from the live sessions."""

    __slots__ = ()

    @classmethod
    def from_sessions(
        cls, sessions: Mapping[ConnectionId, ClientSession]
    ) -> list[Menu]:
        """Return one submenu per identified live session that has callbacks.

        Sessions without an identity or without any callback contribute nothing —
        the menu shows only callbacks a live, named session stands behind. Submenus
        are ordered by label so the bar is stable across reads.
        """
        submenus = [cls._submenu(*parts) for parts in cls._qualifying(sessions)]
        return sorted(submenus, key=lambda menu: menu.label)

    @staticmethod
    def _qualifying(
        sessions: Mapping[ConnectionId, ClientSession],
    ) -> Iterator[_Qualifying]:
        """Yield the parts of each identified session that registered a callback."""
        for connection_id, session in sessions.items():
            identity = session.identity
            if identity is not None and session.callbacks:
                yield connection_id, identity, session.callbacks

    @classmethod
    def _submenu(
        cls,
        connection_id: ConnectionId,
        identity: ClientIdentity,
        callbacks: tuple[SessionCallback, ...],
    ) -> Menu:
        """Build one session's submenu: its identity label over its callback leaves."""
        leaves = [cls._leaf(connection_id, callback) for callback in callbacks]
        ordered: list[MenuAction] = sorted(leaves, key=lambda action: action.label)
        return Menu(label=identity.name, items=list(ordered))

    @staticmethod
    def _leaf(connection_id: ConnectionId, callback: SessionCallback) -> MenuAction:
        """Build a callback leaf whose id round-trips a click back to the session."""
        menu_id = CallbackInvocation(connection_id, callback.id).menu_id
        return MenuAction(id=menu_id, label=callback.label)


@final
class CallbackMenuReplica:
    """The replicator's read of the live session-then-callback submenus, as wire.

    Reads the live sessions fresh on each send and composes them through
    :class:`CallbackMenu`, so the display always receives the sessions in lease at
    send time — the read-at-send discipline the agent bar uses.
    """

    _sessions: LiveSessions
    __slots__ = ("_sessions",)

    def __new__(cls, sessions: LiveSessions) -> Self:
        self = super().__new__(cls)
        self._sessions = sessions
        return self

    def callback_menu_wire(self) -> list[dict[str, object]]:
        """Return the uniform session-then-callback submenus as wire payloads."""
        menus = CallbackMenu.from_sessions(self._sessions.live_sessions())
        return [menu.to_wire() for menu in menus]
