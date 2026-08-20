"""``scene table`` -- construct a composed filterable table scene, server-side.

Text shapes match the shipped ``show_table`` MCP tool byte-for-byte, sharing
:meth:`~punt_lux.commands.scene_show.SceneShowCommand.render_outcome` with
``scene show`` and ``scene dashboard`` -- installing a composed table is the
same ``SceneShown``/``OpError`` outcome as installing a decoded tree.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Self, final

from punt_lux.commands._result import CommandResult
from punt_lux.commands.scene_show import scene_show
from punt_lux.operations import OpError, SceneShown

if TYPE_CHECKING:
    from punt_lux.commands._ports import Ctx, SceneOps
    from punt_lux.operations import RenderTableRequest, Scope


@final
class SceneTableCommand:
    """Construct a composed filterable table scene and install it."""

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    async def execute(
        self,
        ctx: Ctx[SceneOps],
        request: RenderTableRequest | OpError,
        *,
        scope: Scope,
    ) -> SceneShown | OpError:
        """Compose ``request`` into a live table and return the typed outcome."""
        return await asyncio.to_thread(ctx.ops.render_table, request, scope=scope)

    async def __call__(
        self,
        ctx: Ctx[SceneOps],
        request: RenderTableRequest | OpError,
        *,
        scope: Scope,
    ) -> CommandResult:
        """Run :meth:`execute` and render its outcome into the shared envelope."""
        result = await self.execute(ctx, request, scope=scope)
        return scene_show.render_outcome(result)


scene_table: SceneTableCommand = SceneTableCommand()
