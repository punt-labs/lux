"""ServiceRegistry — which connection serves which ``(service, host)`` (DES-107).

A provider client declares a service by name, keyed with the host it declared. One
connection holds a key at a time: the same connection registering again replaces
its own registration, and a different connection claiming a held key is refused
until the holder's registrations are withdrawn. The registry is plain state with no
lock of its own; the lifecycle step that registers and withdraws holds the store
lock, exactly as it does for callbacks.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Self, final

if TYPE_CHECKING:
    from punt_lux.kernel.connection_id import ConnectionId

__all__ = ["ServiceClaim", "ServiceKey", "ServiceRegistry"]

# What a claim did: ``registered`` took or kept the key; ``held`` is a different
# connection already holding it.
ServiceClaim = Literal["registered", "held"]


@final
@dataclass(frozen=True, slots=True, order=True)
class ServiceKey:
    """The service a client serves and the host it declared, ordered for listings."""

    service: str
    host: str


@final
class ServiceRegistry:
    """The ``(service, host)`` keys and the connections that hold them."""

    _holders: dict[ServiceKey, ConnectionId]
    __slots__ = ("_holders",)

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._holders = {}
        return self

    def claim(self, key: ServiceKey, connection_id: ConnectionId) -> ServiceClaim:
        """Take ``key`` for ``connection_id``, or report that another holds it."""
        holder = self._holders.get(key)
        if holder is not None and holder != connection_id:
            return "held"
        self._holders[key] = connection_id
        return "registered"

    def withdraw(self, connection_id: ConnectionId) -> tuple[ServiceKey, ...]:
        """Free every key ``connection_id`` holds; return the keys freed."""
        freed = self.keys_of(connection_id)
        for key in freed:
            del self._holders[key]
        return freed

    def holder(self, key: ServiceKey) -> ConnectionId | None:
        """Return the connection holding ``key``, or ``None`` if it is free."""
        return self._holders.get(key)

    def keys_of(self, connection_id: ConnectionId) -> tuple[ServiceKey, ...]:
        """Return the keys ``connection_id`` holds, in order."""
        return tuple(
            sorted(key for key, held in self._holders.items() if held == connection_id)
        )

    def listing(self) -> tuple[tuple[ServiceKey, ConnectionId], ...]:
        """Return every registration, ordered by key."""
        return tuple(sorted(self._holders.items()))

    def hosts_serving(self, service: str) -> tuple[str, ...]:
        """Return the hosts that serve ``service``, in order."""
        return tuple(
            sorted(key.host for key in self._holders if key.service == service)
        )
