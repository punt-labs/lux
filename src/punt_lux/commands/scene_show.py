"""``scene show`` -- install a whole scene and render the shared result envelope.

Text shapes match the shipped ``show``/``show_table``/``show_dashboard`` MCP
tools byte-for-byte -- ``"shown:<scene_id>"`` and the two error-line shapes
:meth:`SceneShowCommand.render_outcome` renders -- so adapters that already
print those lines pick up the command without changing output. That renderer
is shared by :mod:`punt_lux.commands.scene_table` and
:mod:`punt_lux.commands.scene_dashboard`, whose install path is the same
``render``/``SceneShown`` outcome under a different composition.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Self, final

from punt_lux.commands._result import CommandResult
from punt_lux.operations import OpError, SceneShown

if TYPE_CHECKING:
    from punt_lux.commands._ports import Ctx, SceneOps
    from punt_lux.operations import RenderRequest, Scope


@final
class SceneShowCommand:
    """Install a whole scene and render the shared result envelope."""

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    async def execute(
        self, ctx: Ctx[SceneOps], request: RenderRequest | OpError, *, scope: Scope
    ) -> SceneShown | OpError:
        """Install ``request`` in the caller's scope and return the typed outcome."""
        return await asyncio.to_thread(ctx.ops.render, request, scope=scope)

    async def __call__(
        self, ctx: Ctx[SceneOps], request: RenderRequest | OpError, *, scope: Scope
    ) -> CommandResult:
        """Run :meth:`execute` and render its outcome into the shared envelope."""
        return self.render_outcome(await self.execute(ctx, request, scope=scope))

    @staticmethod
    def render_outcome(result: SceneShown | OpError) -> CommandResult:
        """Render a scene-install outcome shared by ``show``/``table``/``dashboard``.

        A parse-level ``invalid_request`` carries the specific legacy message with
        no prefix; every other rejection (submission gate, undecodable element) is
        a ``"scene not rendered -- "`` error.
        """
        if isinstance(result, SceneShown):
            return CommandResult(
                text=f"shown:{result.scene_id}", json_data={"scene_id": result.scene_id}
            )
        if result.code == "invalid_request":
            text = f"error: {result.reason}"
        else:
            text = f"error: scene not rendered — {result.reason}"
        return CommandResult(
            text=text,
            json_data={"code": result.code, "reason": result.reason},
            error=True,
            exit_code=1,
        )


scene_show: SceneShowCommand = SceneShowCommand()
