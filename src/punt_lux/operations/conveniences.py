"""ConvenienceOperations — typed table and dashboard shorthands over ``render``.

Each convenience composes an element tree from its own typed request and
delegates the install to the one ``render`` operation, so no tree-building lives
in a tool body and there is a single scene-install code path.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, cast, final

from punt_lux.operations.models.common import OpError
from punt_lux.operations.scene_submission import SceneSubmission
from punt_lux.protocol.compositions import TableComposition

if TYPE_CHECKING:
    from collections.abc import Sequence

    from punt_lux.domain.element import Element as DomainElement
    from punt_lux.operations.models.dashboard import RenderDashboardRequest
    from punt_lux.operations.models.scene_results import SceneShown
    from punt_lux.operations.models.table import RenderTableRequest
    from punt_lux.operations.scenes import SceneOperations
    from punt_lux.operations.scope import Scope

__all__ = ["ConvenienceOperations"]


@final
class ConvenienceOperations:
    """Compose common scenes and delegate to ``SceneOperations``."""

    _scenes: SceneOperations
    __slots__ = ("_scenes",)

    def __new__(cls, scenes: SceneOperations) -> Self:
        self = super().__new__(cls)
        self._scenes = scenes
        return self

    def render_table(
        self, request: RenderTableRequest | OpError, *, scope: Scope
    ) -> SceneShown | OpError:
        """Construct a table composition as objects and install it.

        The Hub *constructs* the UI (target.md) — a basic grid, or a group with a
        search box, combos, and a selection-bound detail panel wired through a
        shared ``FilteredTableModel`` — then installs it through the same
        validate-and-``show_scene`` path the wire-decode surface uses.
        """
        if isinstance(request, OpError):
            return request
        # Construction boundary: the composition raises ``ValueError`` on a
        # malformed filter/detail shape (the fail-loud guards) and, like the
        # codecs, ``TypeError`` on a wrong-typed wire shape. This never raises
        # through its signature, so — as in ``SceneOperations.render`` — either
        # becomes a rejection the adapter renders, not a traceback out of a tool.
        try:
            roots = TableComposition.build(request.to_spec())
        except (ValueError, TypeError) as exc:
            return OpError(code="rejected", reason=str(exc))
        submission = SceneSubmission.of(
            cast("Sequence[DomainElement]", roots),
            request.scene_id,
            request.presentation(),
            request.frame_ttl(),
        )
        return self._scenes.install(submission, scope=scope)

    def render_dashboard(
        self, request: RenderDashboardRequest | OpError, *, scope: Scope
    ) -> SceneShown | OpError:
        """Compose a metrics/charts/table dashboard scene and render it."""
        if isinstance(request, OpError):
            return request
        return self._scenes.render(request.to_render_request(), scope=scope)
