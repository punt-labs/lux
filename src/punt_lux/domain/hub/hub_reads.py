"""HubReads — the authoritative introspection reads over the Hub store.

The read half of ``HubDisplay``: a scene's roots, element count, and distinct root
owners (each taking the store's read lock, so that discipline stays here), plus the
live client sessions and the repositories they declared. The client registry keeps
its own consistency, so the two client reads take no store lock.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from collections.abc import Mapping

    from punt_lux.domain.element import Element as WireElement
    from punt_lux.domain.hub.client_identity import ClientSession
    from punt_lux.domain.hub.element_index import ElementIndex
    from punt_lux.domain.hub.hub_clients import HubClientRegistry
    from punt_lux.domain.hub.owner import Owner
    from punt_lux.domain.hub.owner_tracker import OwnerTracker
    from punt_lux.domain.hub.store_lock import StoreLock
    from punt_lux.domain.ids import ConnectionId, SceneId

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
        """Return each live Hub session, sweeping any whose lease has lapsed."""
        return self._clients.live_sessions()
