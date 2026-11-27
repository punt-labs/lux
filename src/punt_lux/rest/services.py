"""The service routes — register what a client serves, and list who serves what.

A client that answers typed requests registers the service it serves; any caller
can list the registrations. ``relay`` has no route: it is the call every service's
own routes make, and there is no generic "call any service" route (DES-107).
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Self, final

from fastapi import APIRouter

from punt_lux.commands import Ctx as CommandCtx
from punt_lux.commands.service_ls import service_ls as service_ls_command
from punt_lux.commands.service_register import (
    service_register as service_register_command,
)
from punt_lux.rest.identity import CallerIdentity, OwningScope
from punt_lux.wire.operations import Ok
from punt_lux.wire.operations.service_requests import RegisterServiceRequest
from punt_lux.wire.operations.service_results import ServiceList

if TYPE_CHECKING:
    from punt_lux.operations import Operations
    from punt_lux.rest.status import HttpErrorMap
    from punt_lux.wire.model.client_identity import ClientIdentity
    from punt_lux.wire.ops import ServiceOps

__all__ = ["ServiceRoutes"]


@final
class ServiceRoutes:
    """Routes over the Hub's service registrations."""

    _ops: Operations
    _errors: HttpErrorMap
    _router: APIRouter
    __slots__ = ("_errors", "_ops", "_router")

    def __new__(cls, ops: Operations, errors: HttpErrorMap) -> Self:
        self = super().__new__(cls)
        self._ops = ops
        self._errors = errors
        router = APIRouter(tags=["services"])
        router.add_api_route(
            "/services",
            self.register_service,
            methods=["POST"],
            name="register_service",
        )
        router.add_api_route(
            "/services", self.list_services, methods=["GET"], name="list_services"
        )
        self._router = router
        return self

    @property
    def router(self) -> APIRouter:
        """The router to mount on the app."""
        return self._router

    def _ctx(self, identity: ClientIdentity) -> CommandCtx[ServiceOps]:
        return CommandCtx(ops=self._ops, identity=identity)

    def register_service(
        self,
        request: RegisterServiceRequest,
        scope: OwningScope,
        identity: CallerIdentity,
    ) -> Ok:
        """Register the service the calling identity serves.

        Needs a live listen leg and an identity, like a menu callback: an
        unidentified request is challenged by ``RestCaller.resolve_scope`` with the
        same 401 a scene write gets, and a connection with no leg is refused 403.
        """
        return self._errors.respond(
            asyncio.run(
                service_register_command.execute(
                    self._ctx(identity), request, scope=scope
                )
            )
        )

    def list_services(
        self, scope: OwningScope, identity: CallerIdentity
    ) -> ServiceList:
        """Return every registration, ordered by service then host."""
        return self._errors.respond(
            asyncio.run(service_ls_command.execute(self._ctx(identity), scope=scope))
        )
