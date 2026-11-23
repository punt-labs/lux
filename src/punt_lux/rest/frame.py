"""Route frame content removal to the Hub under the caller's ownership scope."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from fastapi import APIRouter

from punt_lux.operations import Ok
from punt_lux.rest.identity import OwningScope

if TYPE_CHECKING:
    from punt_lux.operations import Operations
    from punt_lux.rest.route_deps import RouteDeps
    from punt_lux.rest.status import HttpErrorMap


__all__ = ["FrameRoutes"]


@final
class FrameRoutes:
    """Routes that remove the caller's own frame's content."""

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
            "/display/frames/{frame_id}/remove", self.remove_frame, methods=["POST"]
        )
        self._router = router
        return self

    @property
    def router(self) -> APIRouter:
        """The router to mount on the app."""
        return self._router

    def remove_frame(self, frame_id: str, scope: OwningScope) -> Ok:
        """Remove the caller's own frame content: tear down its scenes (DES-057/086)."""
        return self._errors.respond(self._ops.remove_frame(frame_id, scope=scope))
