"""The menu routes — reads and writes of the Hub-owned menu bar.

Menus are UI the agent submitted, so the Hub owns them: the writes are plain Hub
writes the replicator pushes, and the read is Hub-authoritative. Each handler
binds its request, calls one operation, and maps the result.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Annotated, Self, final

from fastapi import APIRouter, Depends

from punt_lux.commands import (
    CallbackRegisterOps,
    Ctx as CommandCtx,
    MenuOps,
    callback_register as callback_register_command,
    menu_ls as menu_ls_command,
    menu_set as menu_set_command,
)
from punt_lux.operations import MenuList, Ok, Scope, SetMenuRequest
from punt_lux.operations.models.callbacks import RegisterCallbackRequest
from punt_lux.rest.identity import resolve_identity, resolve_scope

if TYPE_CHECKING:
    from punt_lux.domain.hub.client_identity import ClientIdentity
    from punt_lux.operations import Operations
    from punt_lux.rest.status import HttpErrorMap

__all__ = ["MenuRoutes"]
_OwningScope = Annotated[Scope, Depends(resolve_scope)]
_CallerIdentity = Annotated["ClientIdentity", Depends(resolve_identity)]


@final
class MenuRoutes:
    """Routes over the Hub-owned menu registry."""

    _ops: Operations
    _errors: HttpErrorMap
    _router: APIRouter
    __slots__ = ("_errors", "_ops", "_router")

    def __new__(cls, ops: Operations, errors: HttpErrorMap) -> Self:
        self = super().__new__(cls)
        self._ops = ops
        self._errors = errors
        router = APIRouter(tags=["menus"])
        router.add_api_route(
            "/menus", self.list_menus, methods=["GET"], name="list_menus"
        )
        router.add_api_route(
            "/menus",
            self.set_menu,
            methods=["PUT"],
            name="set_menu",
            dependencies=[Depends(resolve_scope)],
        )
        router.add_api_route(
            "/menus/callbacks",
            self.register_callback,
            methods=["POST"],
            name="register_callback",
        )
        self._router = router
        return self

    @property
    def router(self) -> APIRouter:
        """The router to mount on the app."""
        return self._router

    def _menu_ctx(self, identity: ClientIdentity) -> CommandCtx[MenuOps]:
        return CommandCtx(ops=self._ops, identity=identity)

    def _callback_ctx(
        self, identity: ClientIdentity
    ) -> CommandCtx[CallbackRegisterOps]:
        return CommandCtx(ops=self._ops, identity=identity)

    def list_menus(self, identity: _CallerIdentity) -> MenuList:
        """Return the Hub-authoritative menu bar."""
        return self._errors.respond(
            asyncio.run(menu_ls_command.execute(self._menu_ctx(identity)))
        )

    def set_menu(self, request: SetMenuRequest, identity: _CallerIdentity) -> Ok:
        """Replace the agent-defined menu bar; the replicator pushes it.

        Identity is required (declared via the router's ``dependencies``): the
        menu bar is Hub state a real caller owns, so a request with no identity
        is refused with the same 401 a scene write meets (DES-057).
        """
        return self._errors.respond(
            asyncio.run(menu_set_command.execute(self._menu_ctx(identity), request))
        )

    def register_callback(
        self,
        request: RegisterCallbackRequest,
        scope: _OwningScope,
        identity: _CallerIdentity,
    ) -> Ok:
        """Register one menu callback for the calling identity; the replicator pushes.

        The write owns a menu item, so an unidentified request is refused with the
        identify challenge ``resolve_scope`` raises — the same 401 a scene write gets.
        """
        return self._errors.respond(
            asyncio.run(
                callback_register_command.execute(
                    self._callback_ctx(identity), request, scope=scope
                )
            )
        )
