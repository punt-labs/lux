"""ServiceDirectory — who may serve a service, and who does (DES-107).

A client registers a service by name; the key is ``(service, host)`` with the host
its identity declared. The directory owns the registry and the gate a registration
passes: the connection must hold a live listen leg and an identity, as a menu
callback's does. The lifecycle holds the store lock around every call, so the leg
read and the claim are one step.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, Self, final

from punt_lux.hub.service_registry import ServiceKey, ServiceRegistry

if TYPE_CHECKING:
    from collections.abc import Callable

    from punt_lux.hub.callback_ports import CallbackListener
    from punt_lux.hub.hub_clients import HubClientRegistry
    from punt_lux.kernel.connection_id import ConnectionId

__all__ = ["ServiceDirectory", "ServiceRegistration"]

# What registering did: the registry's own claim outcomes, plus the two refusals a
# callback registration shares -- no leg to push to, and no identity.
ServiceRegistration = Literal["registered", "held", "superseded", "declined"]


@final
class ServiceDirectory:
    """The registry of services, and the gate a registration passes."""

    _clients: HubClientRegistry
    _clock: Callable[[], float]
    _registry: ServiceRegistry
    __slots__ = ("_clients", "_clock", "_registry")

    def __new__(cls, clients: HubClientRegistry, clock: Callable[[], float]) -> Self:
        self = super().__new__(cls)
        self._clients = clients
        self._clock = clock
        self._registry = ServiceRegistry()
        return self

    def register(
        self, connection_id: ConnectionId, service: str
    ) -> ServiceRegistration:
        """Register ``service`` for the connection, keyed by its declared host.

        A connection with no leg is ``superseded``; an anonymous or lapsed one is
        ``declined``; a key another connection holds is ``held``.
        """
        session = self._clients.session_of(connection_id)
        if session is None or session.listener is None:
            return "superseded"
        identity = session.identity
        if identity is None or not session.is_live(self._clock()):
            return "declined"
        return self._registry.claim(
            ServiceKey(service, identity.host), connection_id, session.listener
        )

    def withdraw(self, connection_id: ConnectionId) -> None:
        """Free every key the connection holds."""
        self._registry.withdraw(connection_id)

    def leg_serving(self, key: ServiceKey) -> CallbackListener | None:
        """Return the leg that registered ``key``, or ``None`` if nothing does."""
        return self._registry.leg_of(key)

    def hosts_serving(self, service: str) -> tuple[str, ...]:
        """Return the hosts that serve ``service``, in order."""
        return self._registry.hosts_serving(service)

    def listing(self) -> tuple[tuple[ServiceKey, ConnectionId], ...]:
        """Return every registration, ordered by key."""
        return self._registry.listing()
