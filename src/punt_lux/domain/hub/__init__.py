"""Hub domain package: connection registry, session indexes, locks.

The Hub is the asyncio-resident process state that owns the display
connection and (in subsequent commits) the io-model index, the
subscription registry, and the dispatcher. ``tools/`` is a thin
transport adapter that calls into this package; no state lives there.
"""

from __future__ import annotations

from punt_lux.domain.hub.clients import ClientRegistry, client_registry
from punt_lux.domain.hub.element_index import ElementIndex
from punt_lux.domain.hub.hub import Hub, hub
from punt_lux.domain.hub.hub_clients import HubClientRegistry
from punt_lux.domain.hub.hub_display import (
    HubDisplay,
    UnknownElementError,
    UnknownSceneError,
    hub_display,
)
from punt_lux.domain.hub.lifecycle import disconnect_connection
from punt_lux.domain.hub.owner_tracker import OwnerTracker
from punt_lux.domain.hub.root_registry import RootRegistry
from punt_lux.domain.hub.subscription_registry import Handler, SubscriptionRegistry

__all__ = [
    "ClientRegistry",
    "ElementIndex",
    "Handler",
    "Hub",
    "HubClientRegistry",
    "HubDisplay",
    "OwnerTracker",
    "RootRegistry",
    "SubscriptionRegistry",
    "UnknownElementError",
    "UnknownSceneError",
    "client_registry",
    "disconnect_connection",
    "hub",
    "hub_display",
]
