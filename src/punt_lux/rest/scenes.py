"""The scene and client routes — the Hub-authoritative reads and writes.

Every handler binds its request, calls one operation on the injected facade, and
hands the typed result to the shared error map. No handler touches the store,
runs a gate, or inspects a result beyond that one mapping — the operation decides,
the route translates.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Self, final

from fastapi import APIRouter, Depends, Query

from punt_lux.operations import (
    Cleared,
    ClientList,
    InspectScope,
    OpError,
    RenderDashboardRequest,
    RenderRequest,
    RenderTableRequest,
    SceneInspection,
    SceneList,
    SceneShown,
    Scope,
    UpdateRequest,
)
from punt_lux.rest.identity import resolve_scope

if TYPE_CHECKING:
    from punt_lux.operations import Operations
    from punt_lux.rest.status import HttpErrorMap

__all__ = ["SceneRoutes"]

# The owning scope of a write, resolved per request from its identity headers.
_OwningScope = Annotated[Scope, Depends(resolve_scope)]


@final
class SceneRoutes:
    """Routes over the Hub-authoritative scene store and session registry.

    Each write resolves its owning scope from the request's identity headers via
    the ``resolve_scope`` dependency; the reads are global and carry no scope.
    """

    _ops: Operations
    _errors: HttpErrorMap
    _router: APIRouter
    __slots__ = ("_errors", "_ops", "_router")

    def __new__(cls, ops: Operations, errors: HttpErrorMap) -> Self:
        self = super().__new__(cls)
        self._ops = ops
        self._errors = errors
        router = APIRouter(tags=["scenes"])
        router.add_api_route(
            "/scenes/{scene_id}", self.render, methods=["PUT"], name="render"
        )
        router.add_api_route(
            "/scenes/{scene_id}/table",
            self.render_table,
            methods=["PUT"],
            name="render_table",
        )
        router.add_api_route(
            "/scenes/{scene_id}/dashboard",
            self.render_dashboard,
            methods=["PUT"],
            name="render_dashboard",
        )
        router.add_api_route(
            "/scenes/{scene_id}", self.update, methods=["PATCH"], name="update"
        )
        router.add_api_route("/scenes", self.clear, methods=["DELETE"], name="clear")
        router.add_api_route(
            "/scenes/{scene_id}",
            self.clear_scene,
            methods=["DELETE"],
            name="clear_scene",
        )
        router.add_api_route(
            "/scenes", self.list_scenes, methods=["GET"], name="list_scenes"
        )
        router.add_api_route(
            "/scenes/{scene_id}",
            self.inspect_scene,
            methods=["GET"],
            name="inspect_scene",
        )
        router.add_api_route(
            "/clients", self.list_clients, methods=["GET"], name="list_clients"
        )
        self._router = router
        return self

    @property
    def router(self) -> APIRouter:
        """The router to mount on the app."""
        return self._router

    def render(
        self, scene_id: str, request: RenderRequest, scope: _OwningScope
    ) -> SceneShown:
        """Install a whole scene named by the path; a mismatched body is rejected."""
        if request.scene_id != scene_id:
            reason = f"body scene_id {request.scene_id!r} must match path {scene_id!r}"
            return self._errors.respond(OpError(code="invalid_request", reason=reason))
        return self._errors.respond(self._ops.render(request, scope=scope))

    def render_table(
        self, scene_id: str, request: RenderTableRequest, scope: _OwningScope
    ) -> SceneShown:
        """Construct a composed table scene server-side; the path names it.

        The Hub *constructs* the composition (its filter/selection/detail handlers
        and ``FilteredTableModel``), so the chrome is live — unlike pushing a
        pre-composed element tree through ``render``, whose JSON decode installs only
        the built-in handlers and leaves the composition dead. A mismatched body is
        rejected.
        """
        if request.scene_id != scene_id:
            reason = f"body scene_id {request.scene_id!r} must match path {scene_id!r}"
            return self._errors.respond(OpError(code="invalid_request", reason=reason))
        return self._errors.respond(self._ops.render_table(request, scope=scope))

    def render_dashboard(
        self, scene_id: str, request: RenderDashboardRequest, scope: _OwningScope
    ) -> SceneShown:
        """Construct a dashboard scene server-side; the path names it."""
        if request.scene_id != scene_id:
            reason = f"body scene_id {request.scene_id!r} must match path {scene_id!r}"
            return self._errors.respond(OpError(code="invalid_request", reason=reason))
        return self._errors.respond(self._ops.render_dashboard(request, scope=scope))

    def update(
        self, scene_id: str, request: UpdateRequest, scope: _OwningScope
    ) -> SceneShown:
        """Apply a patch batch to the scene named in the path."""
        return self._errors.respond(self._ops.update(scene_id, request, scope=scope))

    def clear(self, scope: _OwningScope) -> Cleared:
        """Clear every scene the calling identity owns."""
        return self._errors.respond(self._ops.clear(scope=scope))

    def clear_scene(self, scene_id: str, scope: _OwningScope) -> Cleared:
        """Clear just the named scene; unknown or unowned is a 404 / rejection."""
        return self._errors.respond(
            self._ops.clear_scene(scope=scope, scene_id=scene_id)
        )

    def list_scenes(self) -> SceneList:
        """List every live scene and frame from the authoritative store."""
        return self._errors.respond(self._ops.list_scenes())

    def inspect_scene(
        self, scene_id: str, scope: Annotated[InspectScope, Query()]
    ) -> SceneInspection:
        """Return one scene's tree; ``want_mirror``/``want_geometry`` add facts."""
        return self._errors.respond(self._ops.inspect_scene(scene_id, scope))

    def list_clients(self) -> ClientList:
        """List the Hub's sessions and their scopes."""
        return self._errors.respond(self._ops.list_clients())
