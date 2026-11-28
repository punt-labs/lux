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
    from punt_lux.hub.callback_ports import CallbackListener
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
    """The ``(service, host)`` keys, the connections that hold them, and their legs.

    A registration records the leg that made it, so a request goes to that leg and
    never to a later one that replaced it on the same connection.
    """

    _holders: dict[ServiceKey, ConnectionId]
    _legs: dict[ServiceKey, CallbackListener]
    __slots__ = ("_holders", "_legs")

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._holders = {}
        self._legs = {}
        return self

    def claim(
        self, key: ServiceKey, connection_id: ConnectionId, leg: CallbackListener
    ) -> ServiceClaim:
        """Take ``key`` for ``connection_id``'s ``leg``, or report who holds it."""
        holder = self._holders.get(key)
        if holder is not None and holder != connection_id:
            return "held"
        self._holders[key] = connection_id
        self._legs[key] = leg
        return "registered"

    def leg_of(self, key: ServiceKey) -> CallbackListener | None:
        """Return the leg that registered ``key``, or ``None`` if it is free."""
        return self._legs.get(key)

    def withdraw(self, connection_id: ConnectionId) -> tuple[ServiceKey, ...]:
        """Free every key ``connection_id`` holds; return the keys freed."""
        freed = self.keys_of(connection_id)
        for key in freed:
            del self._holders[key]
            del self._legs[key]
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
