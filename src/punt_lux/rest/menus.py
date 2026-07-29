"""The menu routes — reads and writes of the Hub-owned menu bar.

Menus are UI the agent submitted, so the Hub owns them: the writes are plain Hub
writes the replicator pushes, and the read is Hub-authoritative. Each handler
binds its request, calls one operation, and maps the result.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Self, final

from fastapi import APIRouter, Depends

from punt_lux.operations import MenuList, Ok, PendingCallbacks, Scope, SetMenuRequest
from punt_lux.operations.models.callbacks import RegisterCallbackRequest
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
            "/menus/callbacks",
            self.register_callback,
            methods=["POST"],
            name="register_callback",
        )
        router.add_api_route(
            "/menus/callbacks/pending",
            self.take_pending_callbacks,
            methods=["GET"],
            name="take_pending_callbacks",
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

    def register_callback(
        self, request: RegisterCallbackRequest, scope: _OwningScope
    ) -> Ok:
        """Register one menu callback for the calling identity; the replicator pushes.

        The write owns a menu item, so an unidentified request is refused with the
        identify challenge ``resolve_scope`` raises — the same 401 a scene write gets.
        """
        return self._errors.respond(self._ops.register_callback(request, scope=scope))

    def take_pending_callbacks(self, scope: _OwningScope) -> PendingCallbacks:
        """Drain and return the callback invocations owed to the calling session.

        The periodic/cron delivery leg: a client that connects in bursts polls this
        for the clicks it missed while away, and the read drains what it returns so
        each invocation is delivered once. It is identity-guarded like a write —
        the caller drains only its own hold — so an unidentified request is refused
        with the identify challenge ``resolve_scope`` raises.
        """
        return self._ops.take_pending_callbacks(scope=scope)
