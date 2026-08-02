"""Build the Clients menu from the live Hub sessions.

The menu nests one way and one way only: ``Clients ▸ <client> ▸ <command>``. One
``Clients`` menu holds one submenu per live client that registered a callback,
named for the client, with that client's commands as the leaves under it. The
rule is uniform — voxd, a session's applet, and an on-demand tool are all clients
and all read the same way, whatever their kind and however many there are — so
there is no case logic, no count threshold, and no species split for a user to
carry. Two clients are never merged: each is its own submenu.

The menu is the live roster made visible. An entry exists exactly while its
client holds a lease, so the same menu that launches a command also answers who
is connected.

The hierarchy is what tells clients apart, so the labels stop trying to. A client
is named for the repository it works in (:attr:`ClientIdentity.menu_label`),
numbered by the roster when two read the same way, rather than for the
connection-distinctness token an applet's declared name carries; and a leaf is
named for the command alone — ``Beads``, not ``lux · lux · #4b97 Beads``.

Every client's submenu carries the Hub's own ``Details`` command below its own
commands, which reports the state of that connection. The wire identity a label
no longer shows is not lost — it moves there, where state belongs.

A leaf's id is the owning connection and the callback joined into one wire id
(:class:`CallbackInvocation`), so a click on the leaf round-trips to exactly the
client that registered it — or, for ``Details``, to the Hub itself.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.hub.client_submenu import ClientSubmenu
from punt_lux.domain.hub.menu_models import Menu

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Mapping

    from punt_lux.domain.hub.client_identity import ClientIdentity
    from punt_lux.domain.hub.client_roster import ClientRoster
    from punt_lux.domain.hub.client_session import ClientSession
    from punt_lux.domain.hub.hub_clients import HubClientRegistry
    from punt_lux.domain.hub.menu_models import MenuEntry
    from punt_lux.domain.ids import ConnectionId

__all__ = ["CallbackMenu", "CallbackMenuReplica"]

# The one menu every client's commands live under.
_CLIENTS_LABEL = "Clients"


@final
class CallbackMenu:
    """Compose ``Clients ▸ <client> ▸ <command>`` from the live sessions."""

    __slots__ = ()

    @classmethod
    def from_sessions(
        cls,
        sessions: Mapping[ConnectionId, ClientSession],
        roster: ClientRoster,
    ) -> list[Menu]:
        """Return the ``Clients`` menu the live sessions' callbacks contribute.

        Sessions without an identity or without any callback contribute nothing —
        the menu shows only commands a live, named client stands behind — and with
        no such client there is no menu, because the menu is composed from clients
        rather than kept as an empty fixture. Submenus are ordered by label so the
        bar is stable across reads.

        The roster is asked for the names of exactly the qualifying clients, so a
        client that has gone releases its name here and one that is merely
        unidentified never takes one.
        """
        names = roster.names_for(dict(cls._qualifying(sessions)))
        return cls._clients_menu(
            ClientSubmenu(connection_id, name, sessions[connection_id].callbacks)
            for connection_id, name in names.items()
        )

    @staticmethod
    def _qualifying(
        sessions: Mapping[ConnectionId, ClientSession],
    ) -> Iterator[tuple[ConnectionId, ClientIdentity]]:
        """Yield the identity of each session that is named and registered a command."""
        for connection_id, session in sessions.items():
            identity = session.identity
            if identity is not None and session.callbacks:
                yield connection_id, identity

    @staticmethod
    def _clients_menu(submenus: Iterable[ClientSubmenu]) -> list[Menu]:
        """Return the one ``Clients`` menu over *submenus*, or nothing when empty."""
        ordered = sorted(submenus, key=lambda submenu: submenu.label)
        if not ordered:
            return []
        clients: list[MenuEntry] = [submenu.menu() for submenu in ordered]
        return [Menu(label=_CLIENTS_LABEL, items=clients)]


@final
class CallbackMenuReplica:
    """The replicator's read of the live Clients menu, as wire.

    Reads the live sessions fresh on each send and composes them through
    :class:`CallbackMenu`, so the display always receives the clients in lease at
    send time — the read-at-send discipline the agent bar uses. The roster comes
    from the same registry the Hub's own ``list_menus`` reads, so the two can
    never disagree about which client is ``lux (2)``.
    """

    _clients: HubClientRegistry
    __slots__ = ("_clients",)

    def __new__(cls, clients: HubClientRegistry) -> Self:
        self = super().__new__(cls)
        self._clients = clients
        return self

    def callback_menu_wire(self) -> list[dict[str, object]]:
        """Return the ``Clients`` menu as wire payloads."""
        menus = CallbackMenu.from_sessions(
            self._clients.live_sessions(), self._clients.roster
        )
        return [menu.to_wire() for menu in menus]
