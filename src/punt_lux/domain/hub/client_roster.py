"""ClientRoster — the names the menu calls the display's clients.

A client's menu name is what a person would call it: the repository it works in,
or what it calls itself when it works in none. Two clients often answer to the
same name — two Claude Code sessions on one repository — so the second is
``lux (2)``, the third ``lux (3)``.

A number exists to separate clients a person can see at once, and only for as
long as there are two of them to separate. So when a name is released, whatever
base it freed goes back to a client still numbered against it: after ``lux``
goes, ``lux (2)`` is simply ``lux`` again. A lone client never wears a number,
which is what a session restart used to leave behind — the outgoing session's
lease outlives it by a minute, the newcomer is numbered against a client that
owns no menu entry, and the number stuck for the whole of the newcomer's
connection.

Stability is what the numbering is otherwise for, and it holds over live
duplicates: while two clients of one name are both here, neither's label ever
changes and the two never swap, because nothing but a *removal* re-derives
anything. A menu entry that renames itself under the pointer is worse than a gap
in the numbering, and the gap is what this leaves — with ``lux``, ``lux (2)`` and
``lux (3)`` here and ``lux`` gone, ``lux (2)`` becomes ``lux`` and ``lux (3)``
keeps its number. One rename per departure, never a cascade: the number's job is
to tell two clients apart, not to count them off without gaps.

The senior holder is the one that moves — the earliest of that base still on the
roster. Seniority is already the rule that decides who takes the plain name when
several arrive together, so falling back uses it too rather than introducing a
second idea of who is first; and it is state the roster has, not something read
back out of a label it printed.

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
is what keeps the two from ever disagreeing, and it is what makes a fallback safe
to do here: the release and the re-derivation are the same critical section, so
the next read — the menu's, or a details frame's — sees the whole of it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.hub.menu_name import MenuName

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from punt_lux.domain.hub.client_identity import ClientIdentity
    from punt_lux.domain.ids import ConnectionId

__all__ = ["ClientRoster"]


@final
class ClientRoster:
    """The menu name each live connection holds, numbered only while twins are here."""

    _names: dict[ConnectionId, MenuName]
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
        names back, and nothing it is given can take a name away or move one.

        The order of *identities* decides who gets the unnumbered name when two
        arrive together; the registry hands them over in connection order, so the
        client that connected first is the plain ``lux``.
        """
        for connection_id, identity in identities.items():
            if connection_id not in self._names:
                self._names[connection_id] = MenuName.unheld(
                    identity.menu_label, self._labels()
                )
        return {
            connection_id: self._names[connection_id].label
            for connection_id in identities
        }

    def release(self, departed: Iterable[ConnectionId]) -> None:
        """Drop the names *departed* held and hand any freed base back to a survivor.

        The registry calls this as it removes the sessions, naming them; a
        connection that held no name is no error, because a session may be swept
        having never been identified and so never named.

        Removal is the one moment a name may move, so the fallback happens here,
        in the same breath: after this returns, no client is numbered against a
        base that nobody holds plainly.
        """
        for connection_id in departed:
            self._names.pop(connection_id, None)
        self._reclaim_freed_bases()

    def held(self) -> dict[ConnectionId, str]:
        """The names held right now, as the last assignment or fallback left them.

        A read, never a write: what the menu last showed is what anything naming a
        client afterwards — a details frame, a log line — must call it.
        """
        return {
            connection_id: name.label for connection_id, name in self._names.items()
        }

    def _reclaim_freed_bases(self) -> None:
        """Give each base nobody holds plainly to its senior numbered client.

        Walked in the order the names were taken, so seniority decides, and against
        a running set of what is held, so the second holder of a base sees the
        first's promotion and keeps its own number. A client already holding its
        plain name finds it in that set and stays put, which is why there is no
        case here for whether a name is numbered.
        """
        held = self._labels()
        promoted: dict[ConnectionId, MenuName] = {}
        for connection_id, name in self._names.items():
            if name.plain.label not in held:
                held.add(name.plain.label)
                promoted[connection_id] = name.plain
        self._names.update(promoted)

    def _labels(self) -> set[str]:
        """Every label held right now — what a new or falling-back name must miss."""
        return {name.label for name in self._names.values()}
