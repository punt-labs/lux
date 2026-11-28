"""The service wire methods a client composes over its REST transport."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.client.rest_http_call import HttpCall
from punt_lux.client.rest_reply import RestReply
from punt_lux.wire.operations import Ok, OpError
from punt_lux.wire.operations.service_results import ServiceList

if TYPE_CHECKING:
    from punt_lux.client.rest_transport import HttpTransport
    from punt_lux.wire.operations import Scope
    from punt_lux.wire.operations.service_requests import RegisterServiceRequest

__all__ = ["_ServiceRestOps"]


@final
class _ServiceRestOps:
    """Wraps the ``/services`` REST routes."""

    _transport: HttpTransport
    _headers: dict[str, str]
    __slots__ = ("_headers", "_transport")

    def __new__(cls, transport: HttpTransport, headers: dict[str, str]) -> Self:
        self = super().__new__(cls)
        self._transport = transport
        self._headers = headers
        return self

    def register_service(
        self, request: RegisterServiceRequest | OpError, *, scope: Scope
    ) -> Ok | OpError:
        """Register the service this identity serves through ``POST /services``.

        A request that failed to parse is returned as is, with no round-trip.
        Requests for the service arrive over this identity's listener stream.
        """
        del scope  # REST composes scope from the identity headers on every request
        if isinstance(request, OpError):
            return request
        call = HttpCall.post("/services", request, self._headers)
        return RestReply(self._transport.request(call)).read(Ok)

    def list_services(self, *, scope: Scope) -> ServiceList | OpError:
        """List which hosts serve which services through ``GET /services``."""
        del scope  # REST composes scope from the identity headers on every request
        call = HttpCall.read("/services", self._headers)
        return RestReply(self._transport.request(call)).read(ServiceList)
