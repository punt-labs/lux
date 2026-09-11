"""AddressBook -- the one place a leaf renderer resolves an item's identity.

The failure mode DES-089 closes is not per-surface: menus, frames, scenes,
and tree nodes each independently risk keying ImGui identity or a title on a
bare label, and each one that does repeats the same bug -- two same-labeled
items collide because nothing above the label namespaced it. One component
owns the fix for every surface at once.

:class:`AddressBook` tracks the live set of connected
:class:`~punt_lux.domain.hub_id.HubId` values and, per Hub, the live set of
connections; computes each rung's *ambiguity* -- a pure cardinality test --
on demand; and, once the Hub rung is shown, reuses the same
collision-numbering machinery ``ClientRoster`` already applies at Rung 2
(:class:`~punt_lux.domain.hub.menu_name.MenuNames`) to compute the Hub
rung's own label text -- "pembroke", then "pembroke (2)" for a second Hub
on the same host. The connection and leaf rungs carry the labels their
caller already resolved: Rung 2's own numbering is settled Hub-side
(``ClientRoster``) before it ever reaches the wire, so AddressBook never
re-numbers it.

Ambiguity and labeling are two different jobs on two different cadences:
ambiguity answers *whether* a rung shows at all, recomputed fresh on every
call from whatever :meth:`note_connection`/:meth:`forget_connection` have
most recently reported live; labeling answers *what* a shown rung's label
reads as, and only changes when a Hub's connection count crosses zero.
"""

from __future__ import annotations

from typing import Self, final

from punt_lux.display.replica.lux_address import LuxAddress, Rung
from punt_lux.domain.hub.menu_name import MenuNames
from punt_lux.domain.hub_id import HubId

__all__ = ["AddressBook"]


@final
class AddressBook:
    """Mint the disambiguated :class:`LuxAddress` every leaf renderer routes through.

    No menu item, frame title, scene entry, or tree-node row may be built
    from a bare label again -- :meth:`address_for` is the one construction
    path.
    """

    _hub_labels: MenuNames[HubId]
    _connections: dict[HubId, set[str]]
    __slots__ = ("_connections", "_hub_labels")

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._hub_labels = MenuNames()
        self._connections = {}
        return self

    def note_connection(self, hub: HubId, connection_key: str) -> None:
        """Record one live connection, taking the Hub's label on its first.

        A Hub becomes live -- and enters :meth:`hub_ambiguous`'s count -- the
        moment it holds one connection, not before.
        """
        if hub not in self._connections:
            self._hub_labels.take(hub, hub.hostname)
            self._connections[hub] = set()
        self._connections[hub].add(connection_key)

    def forget_connection(self, hub: HubId, connection_key: str) -> None:
        """Drop one connection, retiring the Hub's label once none remain.

        Forgetting a connection AddressBook never noted is not an error --
        the same tolerance :meth:`~punt_lux.domain.hub.menu_name.MenuNames.drop`
        already gives a departure it was never told to expect.
        """
        live = self._connections.get(hub)
        if live is None:
            return
        live.discard(connection_key)
        if not live:
            del self._connections[hub]
            self._hub_labels.drop((hub,))

    def address_for(
        self,
        hub: HubId,
        connection_key: str,
        connection_label: str,
        leaf_key: str,
        leaf_label: str,
    ) -> LuxAddress:
        """Mint the address an aggregated item's identity resolves to.

        The Hub rung's label is the collision-numbered name
        :meth:`note_connection` assigned; the connection and leaf rungs pass
        their caller-given labels through unchanged.
        """
        hub_label = self._hub_labels.labels().get(hub, hub.hostname)
        return LuxAddress(
            hub=Rung(hub.wire_token, hub_label),
            connection=Rung(connection_key, connection_label),
            leaf=Rung(leaf_key, leaf_label),
        )

    def hub_ambiguous(self) -> bool:
        """Return whether more than one Hub currently holds a live connection."""
        return len(self._connections) > 1

    def connection_ambiguous(self, hub: HubId) -> bool:
        """Return whether the given Hub currently holds more than one connection."""
        return len(self._connections.get(hub, ())) > 1
