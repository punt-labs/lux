"""The display-mode routes — a project's per-repo display config.

Each handler binds its request, calls one operation, and maps the result. The
config is a repo file the operation reads and writes; the route only translates.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Annotated, Self, final

from fastapi import APIRouter, Depends

from punt_lux.commands import (
    Ctx as CommandCtx,
    DisplayModeOps,
    display_mode_get as display_mode_get_command,
    display_mode_set as display_mode_set_command,
)
from punt_lux.operations import DisplayModeRequest, DisplayModeState
from punt_lux.rest.identity import resolve_identity

if TYPE_CHECKING:
    from punt_lux.domain.hub.client_identity import ClientIdentity
    from punt_lux.operations import Operations
    from punt_lux.rest.status import HttpErrorMap

__all__ = ["DisplayModeRoutes"]

_CallerIdentity = Annotated["ClientIdentity", Depends(resolve_identity)]


@final
class DisplayModeRoutes:
    """Routes over a project's display-mode config file."""

    _ops: Operations
    _errors: HttpErrorMap
    _router: APIRouter
    __slots__ = ("_errors", "_ops", "_router")

    def __new__(cls, ops: Operations, errors: HttpErrorMap) -> Self:
        self = super().__new__(cls)
        self._ops = ops
        self._errors = errors
        router = APIRouter(tags=["display-mode"])
        router.add_api_route(
            "/display-mode",
            self.read_display_mode,
            methods=["GET"],
            name="read_display_mode",
        )
        router.add_api_route(
            "/display-mode",
            self.write_display_mode,
            methods=["PUT"],
            name="write_display_mode",
        )
        self._router = router
        return self

    @property
    def router(self) -> APIRouter:
        """The router to mount on the app."""
        return self._router

    def read_display_mode(
        self, repo: str, identity: _CallerIdentity
    ) -> DisplayModeState:
        """Read a project's display mode; ``repo`` is its absolute path."""
        ctx: CommandCtx[DisplayModeOps] = CommandCtx(ops=self._ops, identity=identity)
        return self._errors.respond(
            asyncio.run(display_mode_get_command.execute(ctx, repo))
        )

    def write_display_mode(
        self, request: DisplayModeRequest, identity: _CallerIdentity
    ) -> DisplayModeState:
        """Write a project's display mode."""
        ctx: CommandCtx[DisplayModeOps] = CommandCtx(ops=self._ops, identity=identity)
        return self._errors.respond(
            asyncio.run(display_mode_set_command.execute(ctx, request))
        )
