"""AddressBook -- the one place a leaf renderer resolves an item's identity.

DES-089 closes a bug every aggregating surface (menu, frame, scene, tree
node) independently risked: keying ImGui identity or a title on a bare
label lets two same-labeled items collide. :class:`AddressBook` tracks the
live set of connected :class:`~punt_lux.domain.hub_id.HubId` values and,
per Hub, the live set of connections; computes each rung's *ambiguity* --
a pure cardinality test, recomputed fresh on every call -- and, once the
Hub rung is shown, reuses the collision-numbering machinery
``ClientRoster`` already applies at Rung 2
(:class:`~punt_lux.domain.menu_name.MenuNames`) to label it -- "pembroke",
then "pembroke (2)" for a second Hub on the same host. The connection and
leaf rungs carry the labels their caller already resolved.
"""

from __future__ import annotations

from typing import Self, final

from punt_lux.display.replica.lux_address import LuxAddress, Rung
from punt_lux.domain.hub_id import HubId
from punt_lux.domain.menu_name import MenuNames

__all__ = ["AddressBook"]


@final
class AddressBook:
    """Mint the disambiguated :class:`LuxAddress` every leaf renderer routes through.

    :meth:`address_for` is the one construction path -- no menu item, frame
    title, scene entry, or tree-node row may be built from a bare label.
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

        ``take`` is already a no-op past a holder's first call, so no
        membership check is needed here.
        """
        self._hub_labels.take(hub, hub.hostname)
        self._connections.setdefault(hub, set()).add(connection_key)

    def forget_connection(self, hub: HubId, connection_key: str) -> None:
        """Drop one connection, retiring the Hub's label once none remain.

        ``drop`` is already a no-op for a holder never given a name, so
        forgetting a connection never noted is not an error either.
        """
        live = self._connections.setdefault(hub, set())
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
        their caller-given labels through unchanged. :class:`LuxAddress`
        itself raises if ``connection_key`` or ``leaf_key`` carries the
        separator its ``hidden_id`` joins rungs on.
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
