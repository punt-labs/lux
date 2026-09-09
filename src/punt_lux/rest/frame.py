"""The frame routes -- close the caller's own frame (lux-03k6).

Split out of :mod:`punt_lux.rest.display` (a proxy for display-process
facts): closing a frame is a Hub-side write with its own ownership rule
(DES-086), not a proxied read, so it gets its own small route class --
the same per-concern split :class:`~punt_lux.rest.app.RestSurface` already
uses for scenes, menus, and display-mode config.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Self, final

from fastapi import APIRouter, Depends

from punt_lux.operations import Ok, Scope
from punt_lux.rest.identity import resolve_scope

if TYPE_CHECKING:
    from punt_lux.operations import Operations
    from punt_lux.rest.route_deps import RouteDeps
    from punt_lux.rest.status import HttpErrorMap

_OwningScope = Annotated[Scope, Depends(resolve_scope)]

__all__ = ["FrameRoutes"]


@final
class FrameRoutes:
    """Routes that close the caller's own frame."""

    _ops: Operations
    _errors: HttpErrorMap
    _router: APIRouter
    __slots__ = ("_errors", "_ops", "_router")

    def __new__(cls, deps: RouteDeps) -> Self:
        self = super().__new__(cls)
        self._ops = deps.ops
        self._errors = deps.errors
        router = APIRouter(tags=["display"])
        router.add_api_route(
            "/display/frames/{frame_id}/close", self.close_frame, methods=["POST"]
        )
        self._router = router
        return self

    @property
    def router(self) -> APIRouter:
        """The router to mount on the app."""
        return self._router

    def close_frame(self, frame_id: str, scope: _OwningScope) -> Ok:
        """Close the caller's own frame: tear down its scenes (DES-057, DES-086)."""
        return self._errors.respond(self._ops.close_frame(frame_id, scope=scope))
