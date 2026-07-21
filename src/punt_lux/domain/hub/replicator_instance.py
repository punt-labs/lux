"""The process-wide ``HubReplicator`` and menu registry, and the wiring for both.

A composition root joining the scene store, the menu registry, the client
registry, and the display lifecycle into the one background writer; luxd starts
and stops it. The menu registry is built here beside the scene store because both
are authoritative Hub state the one worker reads fresh at send time — the menu
scene-pattern the replicator uses. Writes to the registry go through one path
(``MenuOperations``); the presentation layer injects this same instance into the
operations facade, so the worker and the operations share one registry. Kept out
of the package ``__init__`` to avoid an import cycle with the click dispatch,
which reaches these lazily.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from punt_lux.domain.hub.clients import client_registry
from punt_lux.domain.hub.hub_display import hub_display
from punt_lux.domain.hub.menu_registry import HubMenuRegistry
from punt_lux.domain.hub.replicator import HubReplicator
from punt_lux.paths import DisplayPaths

if TYPE_CHECKING:
    from punt_lux.domain.hub.replicator_ports import ClientProvider

__all__ = ["hub_menu_registry", "hub_replicator"]

# The authoritative menu state — read fresh by the replicator worker, written
# only through MenuOperations, injected into the operations facade by tools.py.
hub_menu_registry = HubMenuRegistry()

# DisplayClient satisfies the port at runtime — its show_async takes the concrete
# protocol.Element union every WireElement root is; the cast bridges list invariance.
hub_replicator = HubReplicator(
    hub_display.reader,
    hub_menu_registry,
    cast("ClientProvider", client_registry),
    DisplayPaths(),
)
