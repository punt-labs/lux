"""``scene clear-all`` -- clear every scene the caller owns.

Preserves the shipped ``clear`` MCP tool's exact behavior: it always reports
``"cleared"``, discarding whatever :meth:`~SceneClearAllCommand.execute`
returns. There is no failure mode that clearing every owned scene can hit
that a caller needs to act on differently, so the legacy tool never checked
the result -- this command keeps that behavior rather than inventing a new
error path the shipped surface never had.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.commands._result import CommandResult

if TYPE_CHECKING:
    from punt_lux.commands._result import Ctx, SceneOps
    from punt_lux.operations import Cleared, OpError, Scope


@final
class SceneClearAllCommand:
    """Clear every scene the caller owns."""

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    async def execute(self, ctx: Ctx[SceneOps], *, scope: Scope) -> Cleared | OpError:
        """Clear every scene ``scope`` owns and return the typed outcome."""
        return ctx.ops.clear(scope=scope)

    async def __call__(self, ctx: Ctx[SceneOps], *, scope: Scope) -> CommandResult:
        """Clear every owned scene and report ``"cleared"``, as the legacy tool did."""
        await self.execute(ctx, scope=scope)
        return CommandResult(text="cleared")


scene_clear_all: SceneClearAllCommand = SceneClearAllCommand()
