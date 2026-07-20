"""The process-wide ``HubReplicator`` singleton and the wiring that builds it.

A composition root: it is the one place the replicator's collaborators — the
authoritative store, the client registry, and the display lifecycle — are joined
into the single background writer. Importers take ``hub_replicator`` from here;
luxd starts and stops it. Keeping the construction out of the package
``__init__`` avoids an import cycle with the click dispatch, which reaches this
singleton lazily.
"""

from __future__ import annotations

from punt_lux.domain.hub.clients import client_registry
from punt_lux.domain.hub.hub_display import hub_display
from punt_lux.domain.hub.replicator import HubReplicator
from punt_lux.paths import DisplayPaths

__all__ = ["hub_replicator"]

# The store holds elements typed as the WireElement Protocol that are, at
# runtime, the protocol.Element union DisplayClient sends — the same equivalence
# every send path crosses; list invariance is why the checker cannot see it.
hub_replicator = HubReplicator(
    hub_display,
    client_registry,  # type: ignore[arg-type]  # WireElement ≅ protocol.Element union
    DisplayPaths(),
)
