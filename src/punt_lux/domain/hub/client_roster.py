"""ClientRoster — the names the menu calls the display's clients.

A client's menu name is what a person would call it: the repository it works in,
or what it calls itself when it works in none. Two submenus that read the same
way are told apart with a number, so the second is ``lux (2)`` and the third
``lux (3)``.

Naming is per submenu, not per connection. Two applet connections in one Claude
Code session — ``lux-beads`` and a tool's own applet under the same process —
share a :class:`MenuGroupKey`, so they share one name and contribute one
submenu (DES-067). Every other kind is its own submenu, keyed by connection
id. The DES-064 collision-numbering still fires between two DIFFERENT sessions
in the same repo, which are still ``lux`` and ``lux (2)``.

A number lasts only while there is another submenu to be told apart from, so
releasing the last connection of a group hands its base back to a survivor
still numbered against it. Nothing else moves a label; a menu entry that
renamed itself under the pointer would be worse than the gap a fallback
leaves.

Departure is told to the roster, never inferred by it, and only through a
:class:`RosterRelease`. A release can renumber survivors, which changes the Clients
menu's labels, so it is presence and the presence writes' alone: the roster hands its
:class:`RosterRelease` away exactly once (:meth:`ClientRoster.take_release`), the
release is the only place the write exists, and what the registry hands its readers is
a :class:`RosterNames`, which can only name. Nothing a reader is given can take a name
away or promote anybody. The roster holds no lock and needs none; the registry owns it
and calls it under its own lock.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, Self, final

from punt_lux.domain.hub.menu_group_key import MenuGroupKey
from punt_lux.domain.menu_name import MenuNames

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from punt_lux.domain.hub.client_identity import ClientIdentity
    from punt_lux.domain.ids import ConnectionId

__all__ = ["ClientRoster", "RosterNames", "RosterRelease"]


class RosterNames(Protocol):
    """What a reader of the roster may do: name connections, and read the names held."""

    def names_for(
        self, identities: Mapping[ConnectionId, ClientIdentity]
    ) -> dict[ConnectionId, str]:
        """Return the menu name of every given connection, assigning the new ones."""
        ...


@final
class ClientRoster:
    """The menu name each live connection holds, numbered only across submenus."""

    _names: MenuNames[MenuGroupKey]
    _key_of: dict[ConnectionId, MenuGroupKey]
    _release_taken: bool
    __slots__ = ("_key_of", "_names", "_release_taken")

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._names = MenuNames()
        self._key_of = {}
        self._release_taken = False
        return self

    def names_for(
        self, identities: Mapping[ConnectionId, ClientIdentity]
    ) -> dict[ConnectionId, str]:
        """Return the menu name of every given connection, assigning the new ones.

        A connection already known keeps its group's name; a new one is placed
        in its :class:`MenuGroupKey`, and a new group takes the lowest free
        name for its label. Applet siblings in one session share a group, so
        they return the same name (DES-067). Iteration order decides who gets
        the unnumbered name when several arrive together.
        """
        for connection_id, identity in identities.items():
            self._enrol(connection_id, identity)
        labels = self._names.labels()
        return {cid: labels[self._key_of[cid]] for cid in identities}

    def held(self) -> dict[ConnectionId, str]:
        """The names held right now, as the last assignment or fallback left them."""
        labels = self._names.labels()
        return {cid: labels[key] for cid, key in self._key_of.items()}

    def take_release(self) -> RosterRelease:
        """Hand over the one thing that can drop a connection, once.

        Raises ``ValueError`` on a second ask, so no second holder can renumber
        the survivors.
        """
        if self._release_taken:
            msg = "the roster's release was already handed to the presence writes"
            raise ValueError(msg)
        self._release_taken = True
        return RosterRelease(self, self._names, self._key_of)

    def _enrol(self, cid: ConnectionId, identity: ClientIdentity) -> None:
        """Place *cid* in its group and take a name for that group if it is new."""
        key = MenuGroupKey.of(cid, identity)
        self._key_of.setdefault(cid, key)
        self._names.take(key, identity.menu_label)


@final
class RosterRelease:
    """Drop departed connections from a roster: the write that renumbers survivors."""

    _roster: ClientRoster
    _names: MenuNames[MenuGroupKey]
    _key_of: dict[ConnectionId, MenuGroupKey]
    __slots__ = ("_key_of", "_names", "_roster")

    def __new__(
        cls,
        roster: ClientRoster,
        names: MenuNames[MenuGroupKey],
        key_of: dict[ConnectionId, MenuGroupKey],
    ) -> Self:
        self = super().__new__(cls)
        self._roster = roster
        self._names = names
        self._key_of = key_of
        return self

    def release(self, departed: Iterable[ConnectionId]) -> frozenset[ConnectionId]:
        """Drop *departed* connections and free any group whose last member left.

        A group whose last connection departs frees its base, which is handed
        on to a survivor still numbered against it. Returns the survivors whose
        held name that hand-over changed, so their windows can be retitled.
        Releasing a connection the roster never named is no error.
        """
        before = self._roster.held()
        freed = {
            k for cid in departed if (k := self._key_of.pop(cid, None)) is not None
        }
        self._names.drop(freed - set(self._key_of.values()))
        # A name now held that was not held before: the pairs that moved.
        return frozenset(cid for cid, _ in self._roster.held().items() - before.items())
