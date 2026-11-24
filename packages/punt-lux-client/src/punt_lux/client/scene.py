"""``client.scene.*`` -- the noun-grouped Scene accessor over the operation ports."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from punt_lux.wire.operations import (
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
    from punt_lux.wire.ops import SceneOps


@final
class SceneAccessor:
    """Manage and inspect the scenes this client can access."""

    _ops: SceneOps
    _scope: Scope
    __slots__ = ("_ops", "_scope")

    def __new__(cls, ops: SceneOps, scope: Scope) -> Self:
        """Bind scene operations to the caller's identity and scope."""
        self = super().__new__(cls)
        self._ops = ops
        self._scope = scope
        return self

    async def show(self, request: RenderRequest | OpError) -> SceneShown | OpError:
        """Install or replace a scene owned by the caller."""
        return await asyncio.to_thread(self._ops.render, request, scope=self._scope)

    async def update(
        self, scene_id: str, request: UpdateRequest | OpError
    ) -> SceneShown | OpError:
        """Patch elements in place on an installed scene."""
        return await asyncio.to_thread(
            self._ops.update, scene_id, request, scope=self._scope
        )

    async def clear(self, scene_id: str) -> Cleared | OpError:
        """Remove one scene owned by the caller."""
        return await asyncio.to_thread(
            self._ops.clear_scene, scene_id=scene_id, scope=self._scope
        )

    async def clear_all(self) -> Cleared | OpError:
        """Remove every scene owned by the caller."""
        return await asyncio.to_thread(self._ops.clear, scope=self._scope)

    async def inspect(
        self, scene_id: str, facts: InspectScope
    ) -> SceneInspection | OpError:
        """Return the caller's own scene tree for introspection."""
        return await asyncio.to_thread(
            self._ops.inspect_scene, scene_id, scope=self._scope, facts=facts
        )

    async def ls(self) -> SceneList | OpError:
        """List every live scene and frame from the authoritative store."""
        return await asyncio.to_thread(self._ops.list_scenes)

    async def table(
        self, request: RenderTableRequest | OpError
    ) -> SceneShown | OpError:
        """Render a filterable table scene (composite convenience)."""
        return await asyncio.to_thread(
            self._ops.render_table, request, scope=self._scope
        )

    async def dashboard(
        self, request: RenderDashboardRequest | OpError
    ) -> SceneShown | OpError:
        """Render a dashboard scene (composite convenience)."""
        return await asyncio.to_thread(
            self._ops.render_dashboard, request, scope=self._scope
        )
