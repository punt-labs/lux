"""``scene dashboard`` -- construct a composed dashboard scene, server-side.

Text shapes match the shipped ``show_dashboard`` MCP tool byte-for-byte,
sharing :meth:`~punt_lux.commands.scene_show.SceneShowCommand.render_outcome`
with ``scene show`` and ``scene table``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.commands._result import CommandResult
from punt_lux.commands.scene_show import scene_show
from punt_lux.operations import OpError, SceneShown

if TYPE_CHECKING:
    from punt_lux.commands._ports import Ctx, SceneOps
    from punt_lux.operations import RenderDashboardRequest, Scope


@final
class SceneDashboardCommand:
    """Construct a composed dashboard scene and install it."""

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    async def execute(
        self,
        ctx: Ctx[SceneOps],
        request: RenderDashboardRequest | OpError,
        *,
        scope: Scope,
    ) -> SceneShown | OpError:
        """Compose ``request`` into a live dashboard and return the typed outcome."""
        return ctx.ops.render_dashboard(request, scope=scope)

    async def __call__(
        self,
        ctx: Ctx[SceneOps],
        request: RenderDashboardRequest | OpError,
        *,
        scope: Scope,
    ) -> CommandResult:
        """Run :meth:`execute` and render its outcome into the shared envelope."""
        result = await self.execute(ctx, request, scope=scope)
        return scene_show.render_outcome(result)


scene_dashboard: SceneDashboardCommand = SceneDashboardCommand()
