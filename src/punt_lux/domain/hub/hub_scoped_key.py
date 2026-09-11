"""HubScopedKey -- an aggregated store's real key: a Hub plus its own local id.

Composed as a value type (PY-IC-1), never concatenated into one string and
never a bare tuple: two independently-meaningful fields, kept as two fields,
the same argument :class:`~punt_lux.domain.hub.hub_id.HubId` itself makes for
keeping ``hostname`` and ``pid`` apart rather than joining them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import final

from punt_lux.domain.hub.hub_id import HubId

__all__ = ["HubScopedKey"]


@final
@dataclass(frozen=True, slots=True)
class HubScopedKey:
    """An aggregated store's real key.

    Pairs a Hub's own :class:`HubId` with the Rung-2 id that Hub already
    minted (``ConnectionScopedId.compose``'s result, or
    ``CallbackInvocation.menu_id``). Two entries collide only when they
    share the identical ``(hub, local)`` pair -- never across Hubs, by
    construction of this type. Carries no label -- ``LuxAddress`` carries
    this identical pair again for display, but a store's key answers "is
    this the same slot," never "what should this be called."
    """

    hub: HubId
    local: str
