"""ClientRoster — the names the menu calls the display's clients.

A client's menu name is what a person would call it: the repository it works in,
or what it calls itself when it works in none. Two clients often answer to the
same name — two Claude Code sessions on one repository — so the second is
``lux (2)``, the third ``lux (3)``.

The number is not a function of who is live right now. A client keeps the name it
was given for as long as its connection lasts: if ``lux`` goes and ``lux (2)``
stays, ``lux (2)`` keeps its number rather than being promoted, because a menu
entry that renames itself under the pointer is worse than a gap in the numbering.
That is state, so it lives here — one assignment per connection, held until the
connection is gone.

Nothing has to tell the roster a client left. Every read hands it the connections
that are live, and assignments for connections not in that set are dropped, so a
name is released by the same read that stops asking for it.
"""

from __future__ import annotations

from itertools import count
from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from collections.abc import Mapping

    from punt_lux.domain.hub.client_identity import ClientIdentity
    from punt_lux.domain.ids import ConnectionId

__all__ = ["ClientRoster"]


@final
class ClientRoster:
    """The menu name each live connection holds, stable for its lifetime."""

    _names: dict[ConnectionId, str]
    __slots__ = ("_names",)

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._names = {}
        return self

    def names_for(
        self, identities: Mapping[ConnectionId, ClientIdentity]
    ) -> dict[ConnectionId, str]:
        """Return the menu name of every given connection, assigning the new ones.

        A connection that already holds a name keeps it. A new one takes the name
        its identity reads as, numbered past whatever is already held. Connections
        absent from *identities* have gone, and their names are released here.

        The order of *identities* decides who gets the unnumbered name when two
        arrive together; the registry hands them over in connection order, so the
        client that connected first is the plain ``lux``.
        """
        self._release_departed(identities)
        for connection_id, identity in identities.items():
            if connection_id not in self._names:
                self._names[connection_id] = self._unheld(identity.menu_label)
        return {
            connection_id: self._names[connection_id] for connection_id in identities
        }

    def held(self) -> dict[ConnectionId, str]:
        """The names held right now, as the last read assigned them.

        A read, never an assignment: what the menu last showed is what anything
        naming a client afterwards — a details frame, a log line — must call it.
        """
        return dict(self._names)

    def _release_departed(
        self, identities: Mapping[ConnectionId, ClientIdentity]
    ) -> None:
        """Drop the names of connections that are no longer live."""
        for connection_id in tuple(self._names):
            if connection_id not in identities:
                del self._names[connection_id]

    def _unheld(self, base: str) -> str:
        """Return *base*, or the lowest ``base (n)`` no live connection holds."""
        held = set(self._names.values())
        if base not in held:
            return base
        return next(
            candidate for n in count(2) if (candidate := f"{base} ({n})") not in held
        )
