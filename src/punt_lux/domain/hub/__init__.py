"""Hub domain package: connection registry, session indexes, locks.

The Hub is the asyncio-resident process state that owns the display
connection and (in subsequent commits) the io-model index, the
subscription registry, and the dispatcher. ``tools/`` is a thin
transport adapter that calls into this package; no state lives there.
"""

from __future__ import annotations

from punt_lux.domain.hub.clients import ClientRegistry, client_registry

__all__ = ["ClientRegistry", "client_registry"]
