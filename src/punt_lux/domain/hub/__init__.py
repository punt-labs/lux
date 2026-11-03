"""Hub domain package: connection registry, session indexes, locks.

The Hub is the asyncio-resident process state that owns the display
connection and (as it grows) the element index, the subscription
registry, and the dispatcher. ``tools/`` is a thin
transport adapter that calls into this package; no state lives there.
"""

from __future__ import annotations

from punt_lux.domain.hub.clients import ClientRegistry, client_registry
from punt_lux.domain.hub.element_index import ElementIndex
from punt_lux.domain.hub.hub import Hub, hub
from punt_lux.domain.hub.hub_clients import HubClientRegistry
from punt_lux.domain.hub.hub_store_factory import (
    hub_clients,
    hub_display,
    hub_lifecycle,
)
from punt_lux.domain.hub.lifecycle import disconnect_connection
from punt_lux.domain.hub.owner_tracker import OwnerTracker
from punt_lux.domain.hub.root_registry import RootRegistry
from punt_lux.domain.hub.subscription_registry import Handler, SubscriptionRegistry
from punt_lux.domain.hub.writer_registry import WriterRegistry

__all__ = [
    "ClientRegistry",
    "ElementIndex",
    "Handler",
    "Hub",
    "HubClientRegistry",
    "OwnerTracker",
    "RootRegistry",
    "SubscriptionRegistry",
    "WriterRegistry",
    "client_registry",
    "disconnect_connection",
    "hub",
    "hub_clients",
    "hub_display",
    "hub_lifecycle",
]
