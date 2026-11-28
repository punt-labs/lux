"""ServiceOperations — register a service, list who serves, relay a request.

A provider client registers the service it serves; the Hub finds the connection
serving ``(service, host)``, sends it a typed request over its listen leg and
waits for the one outcome (DES-107). Every outcome has one error code, so a caller
can tell whether the request ran: no provider, a busy provider, a refusal, a
deadline and a lost session are five different answers.

The Hub holds no state of the served service: it keeps the registrations and the
pending calls, and the provider answers for everything else.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, Self, final, runtime_checkable

from punt_lux.hub.call_outcomes import (
    Lost,
    ProviderBusyError,
    Refused,
    Replied,
)
from punt_lux.hub.service_registry import ServiceKey
from punt_lux.kernel.local_host import LocalHost
from punt_lux.wire.operations.common import OpError
from punt_lux.wire.operations.menu_results import Ok
from punt_lux.wire.operations.service_results import (
    RelayReply,
    ServiceEntry,
    ServiceList,
)

if TYPE_CHECKING:
    from punt_lux.hub.call_outcomes import CallOutcome
    from punt_lux.hub.client_calls import PendingCall
    from punt_lux.hub.client_lifecycle import ClientLifecycle
    from punt_lux.hub.hub_clients import HubClientRegistry
    from punt_lux.wire.model.scope import Scope
    from punt_lux.wire.operations.service_requests import (
        RegisterServiceRequest,
        RelayRequest,
    )

__all__ = ["RelayLeg", "ServiceOperations"]


@runtime_checkable
class RelayLeg(Protocol):
    """A listen leg that can send a typed request to its client."""

    def relay(
        self, service: str, operation: str, payload: dict[str, object]
    ) -> PendingCall:
        """Send the request and return the call to await."""
        ...


@final
class ServiceOperations:
    """Register services and relay typed requests to the clients that serve them."""

    _lifecycle: ClientLifecycle
    _clients: HubClientRegistry
    __slots__ = ("_clients", "_lifecycle")

    def __new__(cls, lifecycle: ClientLifecycle, clients: HubClientRegistry) -> Self:
        self = super().__new__(cls)
        self._lifecycle = lifecycle
        self._clients = clients
        return self

    def register_service(
        self, request: RegisterServiceRequest | OpError, *, scope: Scope
    ) -> Ok | OpError:
        """Register the service the caller serves, or return why not."""
        if isinstance(request, OpError):
            return request
        outcome = self._lifecycle.register_service(
            scope.connection_id, request.service, scope.client_host
        )
        if outcome == "registered":
            return Ok()
        if outcome == "held":
            return OpError(
                code="rejected",
                reason=f"another client already serves {request.service!r} here; "
                "it is released when that client disconnects or its lease lapses",
            )
        if outcome == "superseded":
            return OpError(
                code="push_required",
                reason="this connection holds no listen leg, so a request could "
                "never reach it; register from a connection holding luxd's /ws leg",
            )
        return OpError.identification_required(
            "declare an identity to register the service this client serves"
        )

    def list_services(self, *, scope: Scope) -> ServiceList:
        """Return every registration, ordered by service then host."""
        self._lifecycle.contact(scope)
        return ServiceList(
            services=[
                ServiceEntry(service=key.service, host=key.host)
                for key, _ in self._lifecycle.services()
            ]
        )

    def relay(
        self, request: RelayRequest | OpError, *, scope: Scope
    ) -> RelayReply | OpError:
        """Relay ``request`` to the provider of its service and return its reply.

        Blocks the calling thread for at most the call deadline, as a callback
        registration blocks for the store lock; callers run it off the event loop.
        """
        if isinstance(request, OpError):
            return request
        self._lifecycle.contact(scope)
        if self._clients.identity_of(scope.connection_id) is None:
            return OpError.identification_required(
                "declare an identity before relaying a request to a service"
            )
        host = request.host if request.host is not None else LocalHost.name()
        key = ServiceKey(request.service, host)
        leg = self._leg_serving(key)
        if leg is None:
            return self._unavailable(key)
        try:
            call = leg.relay(request.service, request.operation, request.payload)
        except ProviderBusyError:
            return OpError(
                code="rejected", reason=f"provider busy: {self._described(key)}"
            )
        return self._result_of(call.wait(), key)

    def _leg_serving(self, key: ServiceKey) -> RelayLeg | None:
        leg = self._lifecycle.service_leg(key)
        return leg if isinstance(leg, RelayLeg) else None

    def _unavailable(self, key: ServiceKey) -> OpError:
        hosts = self._lifecycle.hosts_serving(key.service)
        answering = ", ".join(hosts) if hosts else "none"
        return OpError(
            code="provider_unavailable",
            reason=f"no client serves {key.service!r} on {key.host!r}; "
            f"hosts that answer: {answering}",
        )

    def _result_of(self, outcome: CallOutcome, key: ServiceKey) -> RelayReply | OpError:
        """Map a call's one outcome to its reply or its error code."""
        if isinstance(outcome, Replied):
            return RelayReply(payload=outcome.payload)
        if isinstance(outcome, Refused):
            return OpError(code=outcome.code, reason=outcome.reason)
        if isinstance(outcome, Lost):
            return OpError(
                code="provider_lost",
                reason=f"{self._described(key)} was lost before it answered",
            )
        return OpError(
            code="timeout", reason=f"{self._described(key)} did not answer in time"
        )

    @staticmethod
    def _described(key: ServiceKey) -> str:
        return f"{key.service} on {key.host}"
