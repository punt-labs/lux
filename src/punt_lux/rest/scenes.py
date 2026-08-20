"""The scene and client routes — the Hub-authoritative reads and writes.

Every handler binds its request, calls one operation on the injected facade, and
hands the typed result to the shared error map. No handler touches the store,
runs a gate, or inspects a result beyond that one mapping — the operation decides,
the route translates.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Annotated, Self, final

from fastapi import APIRouter, Depends, Query

from punt_lux.commands import (
    Ctx as CommandCtx,
    SceneOps,
    SessionOps,
    scene_clear as scene_clear_command,
    scene_clear_all as scene_clear_all_command,
    scene_dashboard as scene_dashboard_command,
    scene_inspect as scene_inspect_command,
    scene_ls as scene_ls_command,
    scene_show as scene_show_command,
    scene_table as scene_table_command,
    scene_update as scene_update_command,
    session_ls as session_ls_command,
)
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
from punt_lux.rest.identity import resolve_identity, resolve_scope

if TYPE_CHECKING:
    from punt_lux.domain.hub.client_identity import ClientIdentity
    from punt_lux.operations import Operations
    from punt_lux.rest.status import HttpErrorMap

__all__ = ["SceneRoutes"]

# The owning scope of a write, resolved per request from its identity headers.
_OwningScope = Annotated[Scope, Depends(resolve_scope)]
# The caller's identity — the real one when declared, ``ANONYMOUS_REST`` for reads.
_CallerIdentity = Annotated["ClientIdentity", Depends(resolve_identity)]


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

    def _ctx(self, identity: ClientIdentity) -> CommandCtx[SceneOps]:
        """Build the scene command context around the caller's real identity.

        A future command that reads ``ctx.identity`` sees the caller's declared
        headers rather than a shared stand-in -- the same identity ``resolve_scope``
        recorded against the scope before this route ever runs.
        """
        return CommandCtx(ops=self._ops, identity=identity)

    def render(
        self,
        scene_id: str,
        request: RenderRequest,
        scope: _OwningScope,
        identity: _CallerIdentity,
    ) -> SceneShown:
        """Install a whole scene named by the path; a mismatched body is rejected."""
        if request.scene_id != scene_id:
            reason = f"body scene_id {request.scene_id!r} must match path {scene_id!r}"
            return self._errors.respond(OpError(code="invalid_request", reason=reason))
        result = asyncio.run(
            scene_show_command.execute(self._ctx(identity), request, scope=scope)
        )
        return self._errors.respond(result)

    def render_table(
        self,
        scene_id: str,
        request: RenderTableRequest,
        scope: _OwningScope,
        identity: _CallerIdentity,
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
        result = asyncio.run(
            scene_table_command.execute(self._ctx(identity), request, scope=scope)
        )
        return self._errors.respond(result)

    def render_dashboard(
        self,
        scene_id: str,
        request: RenderDashboardRequest,
        scope: _OwningScope,
        identity: _CallerIdentity,
    ) -> SceneShown:
        """Construct a dashboard scene server-side; the path names it."""
        if request.scene_id != scene_id:
            reason = f"body scene_id {request.scene_id!r} must match path {scene_id!r}"
            return self._errors.respond(OpError(code="invalid_request", reason=reason))
        result = asyncio.run(
            scene_dashboard_command.execute(self._ctx(identity), request, scope=scope)
        )
        return self._errors.respond(result)

    def update(
        self,
        scene_id: str,
        request: UpdateRequest,
        scope: _OwningScope,
        identity: _CallerIdentity,
    ) -> SceneShown:
        """Apply a patch batch to the scene named in the path."""
        result = asyncio.run(
            scene_update_command.execute(
                self._ctx(identity), scene_id, request, scope=scope
            )
        )
        return self._errors.respond(result)

    def clear(self, scope: _OwningScope, identity: _CallerIdentity) -> Cleared:
        """Clear every scene the calling identity owns."""
        result = asyncio.run(
            scene_clear_all_command.execute(self._ctx(identity), scope=scope)
        )
        return self._errors.respond(result)

    def clear_scene(
        self, scene_id: str, scope: _OwningScope, identity: _CallerIdentity
    ) -> Cleared:
        """Clear just the named scene; unknown or unowned is a 404 / rejection."""
        result = asyncio.run(
            scene_clear_command.execute(self._ctx(identity), scene_id, scope=scope)
        )
        return self._errors.respond(result)

    def list_scenes(self, identity: _CallerIdentity) -> SceneList:
        """List every live scene and frame from the authoritative store."""
        result = asyncio.run(scene_ls_command.execute(self._ctx(identity)))
        return self._errors.respond(result)

    def inspect_scene(
        self,
        scene_id: str,
        scope: _OwningScope,
        identity: _CallerIdentity,
        facts: Annotated[InspectScope, Query()],
    ) -> SceneInspection:
        """Return the caller's own scene tree; ``want_geometry`` adds the painted rects.

        Unlike ``list_scenes``, a single-scene inspection is now caller-scoped
        (DES-086, Decision 5) — the composed lookup needs a connection id, and
        only an identified caller has a stable one. An unidentified request
        gets the same ``identification_required`` challenge a write gets,
        rather than silently resolving no scene it could ever own.
        """
        result = asyncio.run(
            scene_inspect_command.execute(
                self._ctx(identity), scene_id, scope=scope, facts=facts
            )
        )
        return self._errors.respond(result)

    def list_clients(self, identity: _CallerIdentity) -> ClientList:
        """List the Hub's sessions and their scopes."""
        ctx: CommandCtx[SessionOps] = CommandCtx(ops=self._ops, identity=identity)
        return self._errors.respond(asyncio.run(session_ls_command.execute(ctx)))
