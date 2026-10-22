"""Connection-lifecycle cleanup — single entry point for disconnect.

The transport layer (``luxd``) calls ``disconnect_connection`` when an MCP
session ends. ``HubDisplay.drop_connection`` runs the full departure cascade
atomically — registry, ownership, subscriptions, writer, and each
connection's registered transport sink (see
:class:`~punt_lux.domain.hub.departure_cascade.DepartureCascade`) — so this
function is a thin, named entry point onto that one coordinator rather than
a second place the cascade's steps are assembled.

The scenes themselves are never torn down, only released: they stay
standing until a later explicit removal or an unowned-claim reclaim.
"""

from __future__ import annotations

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
) -> None:
    """Depart ``connection_id`` as a Hub client, cascading the full departure.

    The connection's scenes are left installed — nothing is blanked — so
    there is no repaint to mark.

    Defaults to the production singleton; tests pass their own isolated
    ``HubDisplay``.
    """
    hub_display.drop_connection(connection_id)
