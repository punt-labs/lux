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

Nothing here decides that a connection has gone, and nothing here can. The roster
is never handed a picture of who is live, so it has no way to conclude from one
that a connection it cannot see has departed: :meth:`names_for` only ever adds.
A name is dropped by :meth:`release`, called by
:class:`~punt_lux.domain.hub.hub_clients.HubClientRegistry` from the two places a
session is actually removed — the lease sweep and an explicit discard — naming
the connections that went. A reader whose picture of the world is a moment old
therefore cannot destroy a name a fresher reader has just handed out, because
releasing is not something a reader does at all.

The roster holds no lock and needs none. The registry owns it, is its only
caller, and makes every one of those calls under its own lock, beside the
sessions the names belong to. One lock over the names and the sessions together
is what keeps the two from ever disagreeing, and it is the registry's — not a
second lock to order against the first.
"""

from __future__ import annotations

from itertools import count
from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

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
        absent from *identities* mean nothing here: this call adds names and reads
        names back, and nothing it is given can take a name away.

        The order of *identities* decides who gets the unnumbered name when two
        arrive together; the registry hands them over in connection order, so the
        client that connected first is the plain ``lux``.
        """
        for connection_id, identity in identities.items():
            if connection_id not in self._names:
                self._names[connection_id] = self._unheld(identity.menu_label)
        return {
            connection_id: self._names[connection_id] for connection_id in identities
        }

    def release(self, departed: Iterable[ConnectionId]) -> None:
        """Drop the names *departed* held, freeing their numbers for the next arrival.

        The registry calls this as it removes the sessions, naming them; a
        connection that held no name is no error, because a session may be swept
        having never been identified and so never named.
        """
        for connection_id in departed:
            self._names.pop(connection_id, None)

    def held(self) -> dict[ConnectionId, str]:
        """The names held right now, as the last assignment left them.

        A read, never an assignment: what the menu last showed is what anything
        naming a client afterwards — a details frame, a log line — must call it.
        """
        return dict(self._names)

    def _unheld(self, base: str) -> str:
        """Return *base*, or the lowest ``base (n)`` no live connection holds."""
        held = set(self._names.values())
        if base not in held:
            return base
        return next(
            candidate for n in count(2) if (candidate := f"{base} ({n})") not in held
        )
