"""``scene ls`` -- list every live scene and frame from the authoritative store."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Self, final

from punt_lux.commands._faults import render_error
from punt_lux.commands._result import CommandResult
from punt_lux.operations import OpError

if TYPE_CHECKING:
    from punt_lux.commands._ports import Ctx, SceneOps
    from punt_lux.operations import SceneList


@final
class SceneLsCommand:
    """List every live scene and frame from the authoritative store."""

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    async def execute(self, ctx: Ctx[SceneOps]) -> SceneList | OpError:
        """Return every live scene and frame, or an ``OpError`` on transport fault."""
        return await asyncio.to_thread(ctx.ops.list_scenes)

    async def __call__(self, ctx: Ctx[SceneOps]) -> CommandResult:
        """Run :meth:`execute` and render its outcome into the shared envelope."""
        result = await self.execute(ctx)
        if isinstance(result, OpError):
            return render_error(result)
        return CommandResult(
            text=f"scenes:{len(result.scenes)}",
            json_data=result.model_dump(mode="json"),
        )


scene_ls: SceneLsCommand = SceneLsCommand()
