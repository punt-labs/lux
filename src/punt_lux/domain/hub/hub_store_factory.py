"""HubStoreFactory — builds the shared primitives, the client door, and the store."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.hub.client_lifecycle import ClientLifecycle
from punt_lux.domain.hub.departure_cascade import DepartureCascade
from punt_lux.domain.hub.hub import Hub, hub as default_hub
from punt_lux.domain.hub.hub_clients import HubClientRegistry
from punt_lux.domain.hub.hub_display import HubDisplay
from punt_lux.domain.hub.owner_tracker import OwnerTracker
from punt_lux.domain.hub.store_lock import StoreLock

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = ["HubStoreFactory", "hub_clients", "hub_display", "hub_lifecycle"]


@final
class HubStoreFactory:
    """The store, and the door beside it, built over one lock and one ownership map."""

    _clients: HubClientRegistry
    _lifecycle: ClientLifecycle
    _display: HubDisplay
    __slots__ = ("_clients", "_display", "_lifecycle")

    def __new__(
        cls, clock: Callable[[], float] = time.monotonic, hub: Hub = default_hub
    ) -> Self:
        self = super().__new__(cls)
        lock = StoreLock()
        owners = OwnerTracker()
        self._clients = HubClientRegistry(clock)
        self._lifecycle = ClientLifecycle(
            self._clients, owners, DepartureCascade(hub), lock
        )
        self._display = HubDisplay(lock, owners, self._lifecycle, self._clients, clock)
        return self

    @property
    def display(self) -> HubDisplay:
        """The scene store."""
        return self._display

    @property
    def lifecycle(self) -> ClientLifecycle:
        """The door's writes."""
        return self._lifecycle

    @property
    def clients(self) -> HubClientRegistry:
        """The door's reads."""
        return self._clients


# The process's one store and its client door, built once and exported by name.
_store = HubStoreFactory()
hub_display: HubDisplay = _store.display
hub_lifecycle: ClientLifecycle = _store.lifecycle
hub_clients: HubClientRegistry = _store.clients
