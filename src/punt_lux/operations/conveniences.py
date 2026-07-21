"""ConvenienceOperations — typed table and dashboard shorthands over ``render``.

Each convenience composes an element tree from its own typed request and
delegates the install to the one ``render`` operation, so no tree-building lives
in a tool body and there is a single scene-install code path.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.operations.models.common import OpError

if TYPE_CHECKING:
    from punt_lux.operations.models.dashboard import RenderDashboardRequest
    from punt_lux.operations.models.scene_results import SceneShown
    from punt_lux.operations.models.table import RenderTableRequest
    from punt_lux.operations.scenes import SceneOperations
    from punt_lux.operations.scope import Scope

__all__ = ["ConvenienceOperations"]


@final
class ConvenienceOperations:
    """Compose common scenes and delegate to ``SceneOperations.render``."""

    _scenes: SceneOperations
    __slots__ = ("_scenes",)

    def __new__(cls, scenes: SceneOperations) -> Self:
        self = super().__new__(cls)
        self._scenes = scenes
        return self

    def render_table(
        self, request: RenderTableRequest | OpError, *, scope: Scope
    ) -> SceneShown | OpError:
        """Compose a filterable table scene and render it."""
        if isinstance(request, OpError):
            return request
        return self._scenes.render(request.to_render_request(), scope=scope)

    def render_dashboard(
        self, request: RenderDashboardRequest | OpError, *, scope: Scope
    ) -> SceneShown | OpError:
        """Compose a metrics/charts/table dashboard scene and render it."""
        if isinstance(request, OpError):
            return request
        return self._scenes.render(request.to_render_request(), scope=scope)
