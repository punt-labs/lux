"""SceneOperations — render, update, and clear against the authoritative store.

These are the Hub-owned scene mutations. Each takes a typed request and returns
a discriminated result. The store and the replicator are given at construction,
and element decode is a connection-scoped factory the presentation layer wires
in, so the class runs against real collaborators in a test without the process.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, cast, final

from punt_lux.domain.hub.scene_writer import HubSceneWriter
from punt_lux.domain.hub.write_result import WriteRejected
from punt_lux.domain.ids import SceneId
from punt_lux.domain.submission_gate import SubmissionGate
from punt_lux.operations.models.common import OpError
from punt_lux.operations.models.scene_results import Cleared, SceneShown

if TYPE_CHECKING:
    from collections.abc import Sequence

    from punt_lux.domain.element import Element as DomainElement
    from punt_lux.domain.hub.hub_display import HubDisplay
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
        """Install a whole scene, or return why the tree was refused.

        Decodes the wire tree in the caller's scope, rejects any malformed
        submission whole, then installs it and marks it for resend.
        """
        if isinstance(request, OpError):
            return request
        factory = self._element_factory(scope.connection_id)
        # Wire-decode boundary: an undecodable element raises ``ValueError``; the
        # operation never raises through its signature, so a decode failure
        # becomes a rejection the adapter renders like any other.
        try:
            elements: list[WireElement] = [
                factory.element_from_dict(e) for e in request.elements
            ]
        except ValueError as exc:
            return OpError(code="rejected", reason=str(exc))
        rejection = SubmissionGate().first_rejection(
            SceneId(request.scene_id), elements
        )
        if rejection is not None:
            return OpError(code="rejected", reason=rejection)
        self._display.show_scene(
            scope.connection_id,
            SceneId(request.scene_id),
            # WireElement is structurally the domain Element the store installs;
            # the cast bridges list invariance across that crossing (PY-TS-12).
            cast("Sequence[DomainElement]", elements),
            request.presentation(),
        )
        self._replicator.mark_dirty(SceneId(request.scene_id))
        return SceneShown(scene_id=request.scene_id)

    def update(
        self, scene_id: str, request: UpdateRequest | OpError, *, scope: Scope
    ) -> SceneShown | OpError:
        """Apply a patch batch to the store, or return why it was rejected.

        The request's boundary codec already mapped the wire shapes to variants;
        the writer keeps its ownership, field-legality, and structural rejections
        and a rejected batch leaves the store untouched.
        """
        if isinstance(request, OpError):
            return request
        writer = HubSceneWriter(self._display)
        result = writer.apply(scope.connection_id, SceneId(scene_id), request.to_wire())
        if isinstance(result, WriteRejected):
            return OpError(code="rejected", reason=result.reason)
        self._replicator.mark_dirty(SceneId(scene_id))
        return SceneShown(scene_id=scene_id)

    def clear(self, *, scope: Scope) -> Cleared:
        """Remove every scene the caller owns and signal a whole-display blank."""
        HubSceneWriter(self._display).clear(scope.connection_id)
        self._replicator.mark_cleared()
        return Cleared()
