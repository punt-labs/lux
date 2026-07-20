"""The process-wide ``HubReplicator`` singleton and the wiring that builds it.

A composition root joining the store, client registry, and display lifecycle into
the one background writer; luxd starts and stops it. Kept out of the package
``__init__`` to avoid an import cycle with the click dispatch, which reaches this
singleton lazily.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from punt_lux.domain.hub.clients import client_registry
from punt_lux.domain.hub.hub_display import hub_display
from punt_lux.domain.hub.replicator import HubReplicator
from punt_lux.paths import DisplayPaths

if TYPE_CHECKING:
    from punt_lux.domain.hub.replicator_ports import ClientProvider

__all__ = ["hub_replicator"]

# DisplayClient satisfies the port at runtime — its show_async takes the concrete
# protocol.Element union every WireElement root is; the cast bridges list invariance.
hub_replicator = HubReplicator(
    hub_display,
    cast("ClientProvider", client_registry),
    DisplayPaths(),
)
