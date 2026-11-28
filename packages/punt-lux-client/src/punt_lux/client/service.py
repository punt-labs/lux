"""The ``client.service.*`` verbs: register what this client serves, list who serves."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Self, final

from punt_lux.client._rest_services import _ServiceRestOps
from punt_lux.wire.operations.service_requests import RegisterServiceRequest

if TYPE_CHECKING:
    from punt_lux.client._rest_transport import _RestTransport
    from punt_lux.wire.operations import Ok, OpError, Scope
    from punt_lux.wire.operations.service_results import ServiceList
    from punt_lux.wire.ops import ServiceOps


@final
class ServiceAccessor:
    """Register a service and list the registrations, over the session's REST leg."""

    _ops: _ServiceRestOps
    _scope: Scope
    __slots__ = ("_ops", "_scope")

    def __new__(cls, ops: _ServiceRestOps, scope: Scope) -> Self:
        """Bind the accessor to the service wire methods and the caller's scope."""
        self = super().__new__(cls)
        self._ops = ops
        self._scope = scope
        return self

    @classmethod
    def over(cls, rest: _RestTransport, scope: Scope) -> Self:
        """Build the accessor over the REST transport a client composes."""
        return cls(_ServiceRestOps(rest.http, rest.headers), scope)

    @property
    def sync(self) -> ServiceOps:
        """The synchronous service operations, for callers that must not use a loop."""
        return self._ops

    async def register(self, service: str) -> Ok | OpError:
        """Register the service this session serves, keyed by its declared host.

        Needs a live listener on this identity; requests for the service arrive
        there, answered by the listener's ``on_request`` handler.
        """
        request = RegisterServiceRequest.parse(service)
        return await asyncio.to_thread(
            self._ops.register_service, request, scope=self._scope
        )

    async def ls(self) -> ServiceList | OpError:
        """List which hosts serve which services."""
        return await asyncio.to_thread(self._ops.list_services, scope=self._scope)
