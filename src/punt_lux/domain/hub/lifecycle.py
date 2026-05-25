"""Connection-lifecycle cleanup — single entry point for disconnect.

The transport layer (``luxd``) calls ``disconnect_connection`` when a
WebSocket session ends. The function drops the client's HubDisplay
registration, marks every owned root removed (the Element Observer
cascade prunes the rest of the tree), tears down the per-connection
subscription scope and writer binding, and finally invokes the caller's
``on_disconnect`` sink so transport-layer state (e.g. the MCP inbox
queue) is released in the same cascade.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from punt_lux.domain.hub.hub import Hub, hub as default_hub
from punt_lux.domain.hub.hub_display import (
    HubDisplay,
    hub_display as default_hub_display,
)
from punt_lux.domain.ids import ConnectionId

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = ["disconnect_connection"]


def disconnect_connection(
    connection_id: ConnectionId,
    on_disconnect: Callable[[ConnectionId], None],
    *,
    hub_display: HubDisplay = default_hub_display,
    hub: Hub = default_hub,
) -> None:
    """Cascade cleanup for ``connection_id``.

    ``on_disconnect`` is a required callback fired after the domain
    cleanup so the transport layer can release per-session resources
    (MCP inbox queue, file handles, etc.). There is no default sink —
    every caller commits to an explicit cleanup target.

    Defaults for ``hub_display`` and ``hub`` point at the production
    singletons; tests pass their own isolated instances.
    """
    hub_display.drop_connection(connection_id)
    hub.on_disconnect(connection_id)
    on_disconnect(connection_id)
