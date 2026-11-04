"""Connection-lifecycle cleanup — single entry point for disconnect.

The transport layer (``luxd``) calls ``disconnect_connection`` when an MCP
session ends. ``ClientLifecycle.depart`` runs the full departure cascade
atomically — registry, ownership, subscriptions, writer, and each
connection's registered transport sink (see
:class:`~punt_lux.domain.hub.departure_cascade.DepartureCascade`) — so this
function is a thin, named entry point onto that one coordinator rather than
a second place the cascade's steps are assembled.

The scenes themselves are never torn down, only released: they stay
standing until a later explicit removal or an unowned-claim reclaim.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from punt_lux.domain.hub.hub_store_factory import hub_lifecycle as default_lifecycle

if TYPE_CHECKING:
    from punt_lux.domain.hub.client_lifecycle import ClientLifecycle
    from punt_lux.domain.ids import ConnectionId

__all__ = ["disconnect_connection"]


def disconnect_connection(
    connection_id: ConnectionId,
    *,
    lifecycle: ClientLifecycle = default_lifecycle,
) -> None:
    """Depart ``connection_id`` as a Hub client, cascading the full departure.

    The connection's scenes are left installed — nothing is blanked — so
    there is no repaint to mark.

    Defaults to the production singleton's lifecycle; tests pass their own
    isolated one.
    """
    lifecycle.depart(connection_id)
