"""The scene and client routes — the Hub-authoritative reads and writes.

Every handler binds its request, calls one operation on the injected facade, and
hands the typed result to the shared error map. No handler touches the store,
runs a gate, or inspects a result beyond that one mapping — the operation decides,
the route translates.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from fastapi import APIRouter

from punt_lux.operations import (
    Cleared,
    ClientList,
    OpError,
    RenderRequest,
    SceneInspection,
    SceneList,
    SceneShown,
    UpdateRequest,
)

if TYPE_CHECKING:
    from punt_lux.operations import Operations, Scope
    from punt_lux.rest.status import HttpErrorMap

__all__ = ["SceneRoutes"]


@final
class SceneRoutes:
    """Routes over the Hub-authoritative scene store and session registry."""

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
        router = APIRouter(tags=["scenes"])
        router.add_api_route(
            "/scenes/{scene_id}", self.render, methods=["PUT"], name="render"
        )
        router.add_api_route(
            "/scenes/{scene_id}", self.update, methods=["PATCH"], name="update"
        )
        router.add_api_route("/scenes", self.clear, methods=["DELETE"], name="clear")
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

    def render(self, scene_id: str, request: RenderRequest) -> SceneShown:
        """Install a whole scene; the path names it and the body must agree.

        The path ``scene_id`` is authoritative like the PATCH and GET siblings.
        ``RenderRequest`` carries its own ``scene_id`` (its MCP-shared shape), so a
        body naming a different scene is a contradiction the route rejects rather
        than letting the body win.
        """
        if request.scene_id != scene_id:
            reason = (
                f"body scene_id {request.scene_id!r} must match the path {scene_id!r}"
            )
            return self._errors.respond(OpError(code="invalid_request", reason=reason))
        return self._errors.respond(self._ops.render(request, scope=self._scope))

    def update(self, scene_id: str, request: UpdateRequest) -> SceneShown:
        """Apply a patch batch to the scene named in the path."""
        return self._errors.respond(
            self._ops.update(scene_id, request, scope=self._scope)
        )

    def clear(self) -> Cleared:
        """Clear every scene the default scope owns."""
        return self._errors.respond(self._ops.clear(scope=self._scope))

    def list_scenes(self) -> SceneList:
        """List every live scene and frame from the authoritative store."""
        return self._errors.respond(self._ops.list_scenes())

    def inspect_scene(
        self, scene_id: str, *, want_mirror: bool = False
    ) -> SceneInspection:
        """Return one scene's element tree; ``want_mirror`` proxies a display check."""
        return self._errors.respond(
            self._ops.inspect_scene(scene_id, want_mirror=want_mirror)
        )

    def list_clients(self) -> ClientList:
        """List the Hub's sessions and their scopes."""
        return self._errors.respond(self._ops.list_clients())
