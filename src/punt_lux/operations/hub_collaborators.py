"""InboxDepth — the one Hub collaborator ``HubPorts`` gained for introspection."""

from __future__ import annotations

from collections.abc import Callable

from punt_lux.domain.ids import ConnectionId

__all__ = ["InboxDepth"]

# Read the queued-but-undelivered event count for a connection (observational only).
type InboxDepth = Callable[[ConnectionId], int]
