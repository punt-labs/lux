"""``scene inspect`` -- read a caller's own scene tree from the authoritative store."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Self, final

from punt_lux.commands._faults import render_error
from punt_lux.commands._result import CommandResult
from punt_lux.operations import OpError
from punt_lux.operations.models.inspect_scope import HUB_ONLY

if TYPE_CHECKING:
    from punt_lux.commands._ports import Ctx, SceneOps
    from punt_lux.operations import InspectScope, SceneInspection, Scope


@final
class SceneInspectCommand:
    """Read a caller's own scene tree from the authoritative store."""

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    async def execute(
        self,
        ctx: Ctx[SceneOps],
        scene_id: str,
        *,
        scope: Scope,
        facts: InspectScope = HUB_ONLY,
    ) -> SceneInspection | OpError:
        """Return ``scene_id``'s tree, composed against the caller's own scope."""
        return await asyncio.to_thread(
            ctx.ops.inspect_scene, scene_id, scope=scope, facts=facts
        )

    async def __call__(
        self,
        ctx: Ctx[SceneOps],
        scene_id: str,
        *,
        scope: Scope,
        facts: InspectScope = HUB_ONLY,
    ) -> CommandResult:
        """Run :meth:`execute` and render its outcome into the shared envelope."""
        result = await self.execute(ctx, scene_id, scope=scope, facts=facts)
        if isinstance(result, OpError):
            return render_error(result)
        return CommandResult(
            text=f"scene:{result.scene_id}", json_data=result.model_dump(mode="json")
        )


scene_inspect: SceneInspectCommand = SceneInspectCommand()
