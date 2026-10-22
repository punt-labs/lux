"""HubReads — the authoritative introspection reads over the Hub store.

The read half of ``HubDisplay``: an element and its owner, what a connection
installed, a scene's roots, element count, and distinct root owners (each taking the
store's read lock, so that discipline stays here), plus the live client sessions.
The client registry keeps its own consistency, so that read takes no store lock.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.hub.element_index import UnknownElementError

if TYPE_CHECKING:
    from collections.abc import Mapping

    from punt_lux.domain.element import Element as WireElement
    from punt_lux.domain.hub.client_session import ClientSession
    from punt_lux.domain.hub.element_index import ElementIndex
    from punt_lux.domain.hub.hub_clients import HubClientRegistry
    from punt_lux.domain.hub.owner import Owner
    from punt_lux.domain.hub.owner_tracker import OwnerTracker
    from punt_lux.domain.hub.store_lock import StoreLock
    from punt_lux.domain.ids import ConnectionId, ElementId, SceneId

__all__ = ["HubReads"]


@final
class HubReads:
    """Locked, authoritative reads of the store for introspection."""

    _index: ElementIndex
    _owners: OwnerTracker
    _clients: HubClientRegistry
    _lock: StoreLock
    __slots__ = ("_clients", "_index", "_lock", "_owners")

    def __new__(
        cls,
        index: ElementIndex,
        owners: OwnerTracker,
        clients: HubClientRegistry,
        lock: StoreLock,
    ) -> Self:
        self = super().__new__(cls)
        self._index = index
        self._owners = owners
        self._clients = clients
        self._lock = lock
        return self

    def resolve(self, scene_id: SceneId, element_id: ElementId) -> WireElement:
        """Return the indexed Element or raise the matching lookup error."""
        return self._index.lookup(scene_id, element_id)

    def owner_of(self, scene_id: SceneId, element_id: ElementId) -> ConnectionId | None:
        """Return the element's owner, or ``None`` if installed but unowned.

        ``None`` is a distinct, valid state (a departure released it), not an
        error; ``UnknownElementError`` is for an element the index never held.
        """
        with self._lock.read():
            if not self._index.contains(scene_id, element_id):
                raise UnknownElementError(scene_id=scene_id, element_id=element_id)
            owner = self._owners.get(scene_id, element_id)
            return owner.connection_id if owner is not None else None

    def elements_owned_by(
        self, connection_id: ConnectionId
    ) -> tuple[tuple[SceneId, ElementId], ...]:
        """Return every ``(scene, element)`` pair this connection installed."""
        with self._lock.read():
            return self._owners.keys_for(connection_id)

    def scene_roots(self, scene_id: SceneId) -> list[WireElement]:
        """Return non-removed root elements for a scene, read under the lock."""
        with self._lock.read():
            return self._index.scene_roots(scene_id)

    def element_count(self, scene_id: SceneId) -> int:
        """Return the count of non-removed elements in a scene, read under lock."""
        with self._lock.read():
            return self._index.element_count(scene_id)

    def scene_owners(self, scene_id: SceneId) -> tuple[Owner, ...]:
        """Return each scene's distinct root owners (with declared identity),
        first-appearance order; filter(None) drops a root whose owner is unrecorded.
        """
        with self._lock.read():
            roots = self._index.scene_root_items(scene_id)
            owned = (self._owners.get(scene_id, key) for key, _ in roots)
            return tuple(dict.fromkeys(filter(None, owned)))

    def client_sessions(self) -> Mapping[ConnectionId, ClientSession]:
        """Return each live Hub session -- a pure filter, sweeping nobody."""
        return self._clients.live_sessions()
