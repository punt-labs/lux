"""SceneOperations — render, update, and clear a caller's own scenes.

These are the Hub-owned scene mutations as a *caller* makes them. Each takes a
typed request and returns a discriminated result. The store and the replicator
are given at construction, and element decode is a connection-scoped factory the
presentation layer wires in, so the class runs against real collaborators in a
test without the process.

Every operation here is scoped: the caller owns what it writes, and reaching the
Hub at all is that connection's contact, so a show registers the caller's session
and renews its lease. Installing itself belongs to ``SceneInstaller``, which the
Hub also uses to write scenes *for* clients that are not calling — that path
registers nobody, and holding the installer rather than this class is what makes
it unable to.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.hub.scene_writer import HubSceneWriter, SceneScope
from punt_lux.domain.hub.write_result import WriteRejected
from punt_lux.domain.ids import SceneId
from punt_lux.operations.models.common import OpError
from punt_lux.operations.models.scene_results import Cleared, SceneShown
from punt_lux.operations.scene_clearing import SceneClearer
from punt_lux.operations.scene_installer import SceneInstaller
from punt_lux.operations.scene_submission import SceneSubmission
from punt_lux.operations.wire_tree import WireTreeDecoder

if TYPE_CHECKING:
    from punt_lux.domain.hub.hub_display import HubDisplay
    from punt_lux.operations.models.patches import UpdateRequest
    from punt_lux.operations.models.render import RenderRequest
    from punt_lux.operations.ports import DirtyMarker, ElementFactoryFor
    from punt_lux.operations.scope import Scope

__all__ = ["SceneOperations"]


@final
class SceneOperations:
    """Install, patch, and clear the calling connection's scenes in ``HubDisplay``."""

    _display: HubDisplay
    _replicator: DirtyMarker
    _decoder: WireTreeDecoder
    _installer: SceneInstaller
    _clearer: SceneClearer
    __slots__ = ("_clearer", "_decoder", "_display", "_installer", "_replicator")

    def __new__(
        cls,
        display: HubDisplay,
        replicator: DirtyMarker,
        element_factory: ElementFactoryFor,
    ) -> Self:
        self = super().__new__(cls)
        self._display = display
        self._replicator = replicator
        self._decoder = WireTreeDecoder(element_factory)
        self._installer = SceneInstaller(display, replicator)
        self._clearer = SceneClearer(display, replicator)
        return self

    def render(
        self, request: RenderRequest | OpError, *, scope: Scope
    ) -> SceneShown | OpError:
        """Decode the wire tree in the caller's scope, install it, or reject it."""
        if isinstance(request, OpError):
            return request
        elements = self._decoder.decode(request.elements, scope.connection_id)
        if isinstance(elements, OpError):
            return elements
        return self.install(
            SceneSubmission.of(
                elements,
                request.scene_id,
                request.presentation(),
                request.frame_ttl(),
            ),
            scope=scope,
        )

    def install(
        self, submission: SceneSubmission, *, scope: Scope
    ) -> SceneShown | OpError:
        """Install a tree the caller submitted, recording its contact first.

        The shared path for the wire-decode surface (``render``) and the Hub-side
        conveniences that *construct* their tree. Showing a scene is the caller
        reaching the Hub, so the call registers the caller's session and renews its
        lease: a client that only ever shows is still a client, and stays one for
        as long as it keeps showing.
        """
        self._display.register_client(scope.connection_id)
        return self._installer.install(submission, owner=scope.connection_id)

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
        """Blank the caller's scenes — all, or just ``scene_id``.

        Scoped like every operation here: the clearer removes only roots this
        connection owns and reports a scene-scoped miss rather than a false
        ``cleared``.
        """
        return self._clearer.clear(scope.connection_id, scene_id)
