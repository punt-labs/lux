"""``client.scene.*`` -- the noun-grouped Scene accessor over the commands layer."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.commands import (
    scene_clear,
    scene_clear_all,
    scene_dashboard,
    scene_inspect,
    scene_ls,
    scene_show,
    scene_table,
    scene_update,
)
from punt_lux.commands._ports import Ctx

if TYPE_CHECKING:
    from punt_lux.commands._ports import SceneOps
    from punt_lux.domain.hub.client_identity import ClientIdentity
    from punt_lux.operations import (
        Cleared,
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


@final
class SceneAccessor:
    """The ``client.scene.*`` verbs, each awaiting one command singleton."""

    _ops: SceneOps
    _identity: ClientIdentity
    _scope: Scope
    __slots__ = ("_identity", "_ops", "_scope")

    def __new__(cls, ops: SceneOps, identity: ClientIdentity, scope: Scope) -> Self:
        self = super().__new__(cls)
        self._ops = ops
        self._identity = identity
        self._scope = scope
        return self

    def _ctx(self) -> Ctx[SceneOps]:
        return Ctx(ops=self._ops, identity=self._identity)

    async def show(self, request: RenderRequest | OpError) -> SceneShown | OpError:
        """Install or replace a scene owned by the caller."""
        return await scene_show.execute(self._ctx(), request, scope=self._scope)

    async def update(
        self, scene_id: str, request: UpdateRequest | OpError
    ) -> SceneShown | OpError:
        """Patch elements in place on an installed scene."""
        return await scene_update.execute(
            self._ctx(), scene_id, request, scope=self._scope
        )

    async def clear(self, scene_id: str) -> Cleared | OpError:
        """Remove one scene owned by the caller."""
        return await scene_clear.execute(
            self._ctx(), scene_id=scene_id, scope=self._scope
        )

    async def clear_all(self) -> Cleared | OpError:
        """Remove every scene owned by the caller."""
        return await scene_clear_all.execute(self._ctx(), scope=self._scope)

    async def inspect(
        self, scene_id: str, facts: InspectScope
    ) -> SceneInspection | OpError:
        """Return the caller's own scene tree for introspection."""
        return await scene_inspect.execute(
            self._ctx(), scene_id, scope=self._scope, facts=facts
        )

    async def ls(self) -> SceneList | OpError:
        """List every live scene and frame from the authoritative store."""
        return await scene_ls.execute(self._ctx())

    async def table(
        self, request: RenderTableRequest | OpError
    ) -> SceneShown | OpError:
        """Render a filterable table scene (composite convenience)."""
        return await scene_table.execute(self._ctx(), request, scope=self._scope)

    async def dashboard(
        self, request: RenderDashboardRequest | OpError
    ) -> SceneShown | OpError:
        """Render a dashboard scene (composite convenience)."""
        return await scene_dashboard.execute(self._ctx(), request, scope=self._scope)
