"""The menu routes — reads and writes of the Hub-owned menu bar.

Menus are UI the agent submitted, so the Hub owns them: the writes are plain Hub
writes the replicator pushes, and the read is Hub-authoritative. Each handler
binds its request, calls one operation, and maps the result.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Self, final

from fastapi import APIRouter, Depends

from punt_lux.operations import MenuList, Ok, Scope, SetMenuRequest
from punt_lux.operations.models.register_tool import RegisterToolRequest
from punt_lux.rest.identity import resolve_scope

if TYPE_CHECKING:
    from punt_lux.operations import Operations
    from punt_lux.rest.status import HttpErrorMap

__all__ = ["MenuRoutes"]

# The owning scope of a menu write, resolved per request from its identity headers.
_OwningScope = Annotated[Scope, Depends(resolve_scope)]


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
        router.add_api_route("/menus", self.set_menu, methods=["PUT"], name="set_menu")
        router.add_api_route(
            "/menus/items",
            self.register_menu_item,
            methods=["POST"],
            name="register_menu_item",
        )
        self._router = router
        return self

    @property
    def router(self) -> APIRouter:
        """The router to mount on the app."""
        return self._router

    def list_menus(self) -> MenuList:
        """Return the Hub-authoritative menu bar."""
        return self._errors.respond(self._ops.list_menus())

    def set_menu(self, request: SetMenuRequest) -> Ok:
        """Replace the agent-defined menu bar; the replicator pushes it."""
        return self._errors.respond(self._ops.set_menu(request))

    def register_menu_item(
        self, request: RegisterToolRequest, scope: _OwningScope
    ) -> Ok:
        """Register one tool item for the calling identity; the replicator pushes it."""
        return self._errors.respond(self._ops.register_menu_item(request, scope=scope))
