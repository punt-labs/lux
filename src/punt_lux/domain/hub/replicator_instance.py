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

from punt_lux.domain.hub.callback_hold import CallbackRouter
from punt_lux.domain.hub.callback_menu import CallbackMenuReplica
from punt_lux.domain.hub.clients import client_registry
from punt_lux.domain.hub.hub_display import hub_display
from punt_lux.domain.hub.menu_registry import HubMenuRegistry
from punt_lux.domain.hub.replicator import HubReplicator
from punt_lux.paths import DisplayPaths

if TYPE_CHECKING:
    from punt_lux.domain.hub.replicator_ports import ClientProvider

__all__ = ["hub_callback_router", "hub_menu_registry", "hub_replicator"]

# The authoritative menu state — read fresh by the replicator worker, written
# only through MenuOperations, injected into the operations facade by tools.py.
hub_menu_registry = HubMenuRegistry()

# The one process-wide router for menu-callback clicks. Both composition roots
# inject this instance so a click held on one surface is drained on any other; it
# routes against the session registry that lives in the shared HubDisplay.
hub_callback_router = CallbackRouter(hub_display.clients)

# DisplayLink satisfies the port at runtime — its show_async takes the concrete
# protocol.Element union every WireElement root is; the cast bridges list invariance.
# hub_display satisfies QuarantinePort structurally (quarantine / is_quarantined).
hub_replicator = HubReplicator(
    hub_display.reader,
    hub_menu_registry,
    CallbackMenuReplica(hub_display.clients),
    cast("ClientProvider", client_registry),
    DisplayPaths(),
    hub_display,
)

# Closes the bootstrap ordering gap: client_registry (clients.py) is built
# before this replicator exists, so its connect-success hook (DES-068)
# starts with a no-op marker until this wiring runs, right here at import
# time, before any surface starts serving.
client_registry.attach_replicator(hub_replicator)
