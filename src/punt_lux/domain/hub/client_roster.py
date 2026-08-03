"""ClientRoster — the names the menu calls the display's clients.

A client's menu name is what a person would call it: the repository it works in,
or what it calls itself when it works in none. Two clients often answer to the
same name — two Claude Code sessions on one repository — so the second is
``lux (2)``, the third ``lux (3)``. Which name that is at any moment is
:class:`~punt_lux.domain.hub.menu_name.MenuNames`; who is entitled to one, and
when it is given up, is here.

A number lasts only while there is another client to be told apart from, so
releasing a name hands the base it frees back to a client still numbered against
it: ``lux (2)`` left alone is simply ``lux`` again. Nothing else moves a label —
while two clients of one name are both here neither is renamed and the two never
swap — because a removal is the only thing that re-derives anything, and a menu
entry that renames itself under the pointer is worse than the gap a fallback
leaves in the numbering.

Nothing here decides that a connection has gone, and nothing here can. The roster
is never handed a picture of who is live, so it has no way to conclude from one
that a connection it cannot see has departed: :meth:`names_for` only ever adds.
A name is dropped by :meth:`release`, called by
:class:`~punt_lux.domain.hub.hub_clients.HubClientRegistry` from the two places a
session is actually removed — the lease sweep and an explicit discard — naming
the connections that went. A reader whose picture of the world is a moment old
therefore cannot destroy a name a fresher reader has just handed out, nor promote
anybody, because releasing is not something a reader does at all.

The roster holds no lock and needs none. The registry owns it, is its only
caller, and makes every one of those calls under its own lock, beside the
sessions the names belong to. One lock over the names and the sessions together
keeps the two from ever disagreeing, and it is what makes falling back safe here:
a release and the re-derivation it triggers are one critical section, so the next
read — the menu's, or a details frame's — sees the whole of it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.hub.menu_name import MenuNames

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from punt_lux.domain.hub.client_identity import ClientIdentity
    from punt_lux.domain.ids import ConnectionId

__all__ = ["ClientRoster"]


@final
class ClientRoster:
    """The menu name each live connection holds, numbered only while twins are here."""

    _names: MenuNames
    __slots__ = ("_names",)

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._names = MenuNames()
        return self

    def names_for(
        self, identities: Mapping[ConnectionId, ClientIdentity]
    ) -> dict[ConnectionId, str]:
        """Return the menu name of every given connection, assigning the new ones.

        A connection that already holds a name keeps it; a new one takes the name
        its identity reads as, numbered past whatever is already held. Connections
        absent from *identities* mean nothing here: this call adds names and reads
        names back, and nothing it is given takes a name away or moves one.

        The order of *identities* decides who gets the unnumbered name when
        several arrive together — the registry hands them over in connection
        order, so the client that connected first is the plain ``lux``.
        """
        for connection_id, identity in identities.items():
            self._names.take(connection_id, identity.menu_label)
        held = self._names.labels()
        return {connection_id: held[connection_id] for connection_id in identities}

    def release(self, departed: Iterable[ConnectionId]) -> None:
        """Drop the names *departed* held and hand any freed base back to a survivor.

        The registry calls this as it removes the sessions, naming them; a
        connection that held no name is no error, because a session may be swept
        having never been identified and so never named. Removal is the one moment
        a name may move, so the fallback happens here, in the same breath.
        """
        self._names.drop(departed)

    def held(self) -> dict[ConnectionId, str]:
        """The names held right now, as the last assignment or fallback left them."""
        return self._names.labels()
