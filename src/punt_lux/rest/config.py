"""The display-mode routes — a project's per-repo display config.

Each handler binds its request, calls one operation, and maps the result. The
config is a repo file the operation reads and writes; the route only translates.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from fastapi import APIRouter

from punt_lux.operations import DisplayModeRequest, DisplayModeState

if TYPE_CHECKING:
    from punt_lux.operations import Operations
    from punt_lux.rest.status import HttpErrorMap

__all__ = ["DisplayModeRoutes"]


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

    def read_display_mode(self, repo: str) -> DisplayModeState:
        """Read a project's display mode; ``repo`` is its absolute path."""
        return self._errors.respond(self._ops.read_display_mode(repo))

    def write_display_mode(self, request: DisplayModeRequest) -> DisplayModeState:
        """Write a project's display mode."""
        return self._errors.respond(self._ops.write_display_mode(request))
