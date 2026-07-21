"""The menu routes — reads and writes of the Hub-owned menu bar.

Menus are UI the agent submitted, so the Hub owns them: the writes are plain Hub
writes the replicator pushes, and the read is Hub-authoritative. Each handler
binds its request, calls one operation, and maps the result.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from fastapi import APIRouter

from punt_lux.operations import MenuList, Ok, SetMenuRequest
from punt_lux.operations.models.register_tool import RegisterToolRequest

if TYPE_CHECKING:
    from punt_lux.operations import Operations, Scope
    from punt_lux.rest.status import HttpErrorMap

__all__ = ["MenuRoutes"]


@final
class MenuRoutes:
    """Routes over the Hub-owned menu registry."""

    _ops: Operations
    _scope: Scope
    _errors: HttpErrorMap
    _router: APIRouter
    __slots__ = ("_errors", "_ops", "_router", "_scope")

    def __new__(cls, ops: Operations, scope: Scope, errors: HttpErrorMap) -> Self:
        self = super().__new__(cls)
        self._ops = ops
        self._scope = scope
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

    def register_menu_item(self, request: RegisterToolRequest) -> Ok:
        """Register one tool item for the default scope; the replicator pushes it."""
        return self._errors.respond(
            self._ops.register_menu_item(request, scope=self._scope)
        )
