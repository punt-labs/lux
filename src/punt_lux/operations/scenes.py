"""SceneOperations — render, update, and clear against the authoritative store.

These are the Hub-owned scene mutations. Each takes a typed request and returns
a discriminated result. The store and the replicator are given at construction,
and element decode is a connection-scoped factory the presentation layer wires
in, so the class runs against real collaborators in a test without the process.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, cast, final

from punt_lux.domain.hub.scene_writer import HubSceneWriter, SceneScope
from punt_lux.domain.hub.write_result import WriteRejected
from punt_lux.domain.ids import SceneId
from punt_lux.domain.submission_gate import SubmissionGate
from punt_lux.operations.models.common import OpError
from punt_lux.operations.models.scene_results import Cleared, SceneShown

if TYPE_CHECKING:
    from collections.abc import Sequence

    from punt_lux.domain.element import Element as DomainElement
    from punt_lux.domain.hub.hub_display import HubDisplay
    from punt_lux.domain.hub.scene_presentation import ScenePresentation
    from punt_lux.operations.models.patches import UpdateRequest
    from punt_lux.operations.models.render import RenderRequest
    from punt_lux.operations.ports import DirtyMarker, ElementFactoryFor
    from punt_lux.operations.scope import Scope
    from punt_lux.protocol import Element as WireElement

__all__ = ["SceneOperations"]


@final
class SceneOperations:
    """Install, patch, and clear scenes in ``HubDisplay``."""

    _display: HubDisplay
    _replicator: DirtyMarker
    _element_factory: ElementFactoryFor
    __slots__ = ("_display", "_element_factory", "_replicator")

    def __new__(
        cls,
        display: HubDisplay,
        replicator: DirtyMarker,
        element_factory: ElementFactoryFor,
    ) -> Self:
        self = super().__new__(cls)
        self._display = display
        self._replicator = replicator
        self._element_factory = element_factory
        return self

    def render(
        self, request: RenderRequest | OpError, *, scope: Scope
    ) -> SceneShown | OpError:
        """Decode the wire tree in the caller's scope, install it, or reject it."""
        if isinstance(request, OpError):
            return request
        factory = self._element_factory(scope.connection_id)
        # Wire-decode boundary: a malformed element raises ``ValueError``/``TypeError``,
        # each a rejection; the catch wraps only the decode, not ``install`` below,
        # so a store-miss ``KeyError`` still surfaces as the engine bug it is.
        try:
            elements: list[WireElement] = [
                factory.element_from_dict(e) for e in request.elements
            ]
        except (ValueError, TypeError) as exc:
            return OpError(code="rejected", reason=str(exc))
        # WireElement is structurally the domain Element; the cast bridges list
        # invariance across that crossing (PY-TS-12).
        return self.install(
            cast("Sequence[DomainElement]", elements),
            scene_id=request.scene_id,
            presentation=request.presentation(),
            ttl_seconds=request.frame_ttl(),
            scope=scope,
        )

    def install(
        self,
        elements: Sequence[DomainElement],
        *,
        scene_id: str,
        presentation: ScenePresentation,
        ttl_seconds: float | None,
        scope: Scope,
    ) -> SceneShown | OpError:
        """Validate a built element tree and install it, or return why it was refused.

        The shared path for the wire-decode surface (``render``) and the Hub-side
        conveniences that *construct* their tree: same validation walk, same
        ``show_scene`` (target.md — the Hub decodes *or constructs* UI).
        """
        rejection = SubmissionGate().first_rejection(SceneId(scene_id), elements)
        if rejection is not None:
            return OpError(code="rejected", reason=rejection)
        self._display.show_scene(
            scope.connection_id,
            SceneId(scene_id),
            elements,
            presentation,
            ttl_seconds=ttl_seconds,
        )
        self._replicator.mark_dirty(SceneId(scene_id))
        return SceneShown(scene_id=scene_id)

    def update(
        self, scene_id: str, request: UpdateRequest | OpError, *, scope: Scope
    ) -> SceneShown | OpError:
        """Apply a patch batch to the store, or return why it was rejected.

        The writer keeps its ownership and field-legality rejections; a rejected
        batch leaves the store untouched.
        """
        if isinstance(request, OpError):
            return request
        writer = HubSceneWriter(self._display)
        target = SceneScope(scope.connection_id, SceneId(scene_id))
        result = writer.apply(target, request.to_wire())
        if isinstance(result, WriteRejected):
            return OpError(code="rejected", reason=result.reason)
        self._replicator.mark_dirty(SceneId(scene_id))
        return SceneShown(scene_id=scene_id)

    def clear(self, *, scope: Scope, scene_id: str | None = None) -> Cleared | OpError:
        """Blank the caller's scenes — all, or just ``scene_id`` — one scene at a time.

        The writer removes only the caller's roots and marks each emptied scene dirty,
        so nothing else is touched. A scene-scoped clear that removes nothing must not
        lie ``cleared``; it reports ``not_found`` or a rejection instead. The no-arg
        clear removing nothing stays a settled no-op.
        """
        target = SceneId(scene_id) if scene_id is not None else None
        touched = HubSceneWriter(self._display).clear(scope.connection_id, target)
        if target is not None and not touched:
            return self._scoped_clear_miss(target)
        self._mark_dirty_all(touched)
        return Cleared()

    def _scoped_clear_miss(self, scene_id: SceneId) -> OpError:
        """Say why a scene-scoped clear removed nothing: unknown scene, or unowned.

        No non-removed root means the scene is unknown (the ``not_found`` inspect_scene
        returns); roots present but none the caller owns is an ownership rejection.
        """
        name = str(scene_id)
        if not self._display.scene_roots(scene_id):
            return OpError(code="not_found", reason=f"scene {name!r} not found")
        return OpError(code="rejected", reason=f"scene {name!r} holds nothing you own")

    def _mark_dirty_all(self, scenes: frozenset[SceneId]) -> None:
        """Mark every scene in ``scenes`` for resend."""
        for scene_id in scenes:
            self._replicator.mark_dirty(scene_id)
