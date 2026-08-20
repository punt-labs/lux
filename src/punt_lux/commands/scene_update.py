"""``scene update`` -- patch a scene and render the shared result envelope.

Text shapes match the shipped ``update`` MCP tool byte-for-byte --
``"shown:<scene_id>"`` / ``"error: scene not updated — <reason>"``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.commands._result import CommandResult
from punt_lux.operations import OpError, SceneShown

if TYPE_CHECKING:
    from punt_lux.commands._ports import Ctx, SceneOps
    from punt_lux.operations import Scope, UpdateRequest


@final
class SceneUpdateCommand:
    """Apply a patch batch to a scene and render the shared result envelope."""

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    async def execute(
        self,
        ctx: Ctx[SceneOps],
        scene_id: str,
        request: UpdateRequest | OpError,
        *,
        scope: Scope,
    ) -> SceneShown | OpError:
        """Apply ``request`` to ``scene_id`` and return the typed outcome."""
        return ctx.ops.update(scene_id, request, scope=scope)

    async def __call__(
        self,
        ctx: Ctx[SceneOps],
        scene_id: str,
        request: UpdateRequest | OpError,
        *,
        scope: Scope,
    ) -> CommandResult:
        """Run :meth:`execute` and render its outcome into the shared envelope."""
        result = await self.execute(ctx, scene_id, request, scope=scope)
        if isinstance(result, SceneShown):
            return CommandResult(
                text=f"shown:{result.scene_id}", json_data={"scene_id": result.scene_id}
            )
        return CommandResult(
            text=f"error: scene not updated — {result.reason}",
            json_data={"code": result.code, "reason": result.reason},
            error=True,
            exit_code=1,
        )


scene_update: SceneUpdateCommand = SceneUpdateCommand()
