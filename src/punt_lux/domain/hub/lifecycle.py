"""Connection-lifecycle cleanup — single entry point for disconnect.

The transport layer (``luxd``) calls ``disconnect_connection`` when a
WebSocket session ends. The function drops the client's HubDisplay
registration, marks every owned root removed (the Element Observer
cascade prunes the rest of the tree), and tears down the per-connection
subscription scope and writer binding.
"""

from __future__ import annotations

from punt_lux.domain.hub.hub import Hub, hub as default_hub
from punt_lux.domain.hub.hub_display import (
    HubDisplay,
    hub_display as default_hub_display,
)
from punt_lux.domain.ids import ConnectionId

__all__ = ["disconnect_connection"]


def disconnect_connection(
    connection_id: ConnectionId,
    *,
    hub_display: HubDisplay = default_hub_display,
    hub: Hub = default_hub,
) -> None:
    """Cascade cleanup for ``connection_id``.

    Defaults point at the production singletons; tests pass their own
    isolated instances.
    """
    hub_display.drop_connection(connection_id)
    hub.on_disconnect(connection_id)
