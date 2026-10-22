"""ClientLifecycleFactory — assembles the client lifecycle and what it owns.

The lifecycle owns the session registry and the departure cascade; the store that
hosts it supplies only the Hub, the clock, and the shared ownership and lock. Keeping
the assembly here leaves the store free of both collaborators.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.hub.client_lifecycle import ClientLifecycle
from punt_lux.domain.hub.departure_cascade import DepartureCascade
from punt_lux.domain.hub.hub_clients import HubClientRegistry

if TYPE_CHECKING:
    from collections.abc import Callable

    from punt_lux.domain.hub.hub import Hub
    from punt_lux.domain.hub.owner_tracker import OwnerTracker
    from punt_lux.domain.hub.store_lock import StoreLock

__all__ = ["ClientLifecycleFactory"]


@final
class ClientLifecycleFactory:
    """Builds a ``ClientLifecycle`` over a Hub and a lease clock."""

    _hub: Hub
    _registry: HubClientRegistry
    __slots__ = ("_hub", "_registry")

    def __new__(cls, hub: Hub, clock: Callable[[], float]) -> Self:
        self = super().__new__(cls)
        self._hub = hub
        self._registry = HubClientRegistry(clock)
        return self

    @property
    def registry(self) -> HubClientRegistry:
        """Return the session registry the built lifecycle writes to."""
        return self._registry

    def build(self, owners: OwnerTracker, lock: StoreLock) -> ClientLifecycle:
        """Return a lifecycle over the registry and a fresh departure cascade."""
        return ClientLifecycle(
            self._registry, owners, DepartureCascade(self._hub), lock
        )
