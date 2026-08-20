"""``scene clear`` -- clear one scene and render the shared result envelope.

Text shapes match the shipped ``clear_scene`` MCP tool byte-for-byte --
``"cleared"`` on success, the shared fault line
(:func:`punt_lux.commands._faults.render_fault`) on an unknown or unowned
scene -- so an unmistyped id can never look like a successful clear.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Self, final

from punt_lux.commands._faults import render_fault
from punt_lux.commands._result import CommandResult
from punt_lux.operations import Cleared, OpError

if TYPE_CHECKING:
    from punt_lux.commands._ports import Ctx, SceneOps
    from punt_lux.operations import Scope


@final
class SceneClearCommand:
    """Clear one scene and render the shared result envelope."""

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    async def execute(
        self, ctx: Ctx[SceneOps], scene_id: str, *, scope: Scope
    ) -> Cleared | OpError:
        """Clear ``scene_id`` and return the typed outcome."""
        return await asyncio.to_thread(
            ctx.ops.clear_scene, scope=scope, scene_id=scene_id
        )

    async def __call__(
        self, ctx: Ctx[SceneOps], scene_id: str, *, scope: Scope
    ) -> CommandResult:
        """Run :meth:`execute` and render its outcome into the shared envelope."""
        result = await self.execute(ctx, scene_id, scope=scope)
        if isinstance(result, OpError):
            return render_fault(result)
        return CommandResult(text="cleared")


scene_clear: SceneClearCommand = SceneClearCommand()
