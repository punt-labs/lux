"""SceneInstaller — validate a built element tree, install it, mark it for resend.

The one install: every scene reaches ``HubDisplay`` through here, whether a
client submitted it over the wire or the Hub constructed it itself (target.md —
the Hub decodes *or constructs* UI). It runs the submission gate first, so a
tree with any invalid element is refused whole and nothing partial is installed.

Installing registers nobody. The owner named here is attribution — whose scene
this is, so it appears among that client's scenes and goes when they are cleared
— and attribution is not contact. The Hub writes per-client scenes for clients
that are not calling and may already have gone; an install that registered its
owner would recreate the session that client's departure removed, leaving a
client in the roster with nothing on the other end of it. A connection that is
really there says so through its own arrival, which is
:meth:`~punt_lux.operations.scenes.SceneOperations.install`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.submission_gate import SubmissionGate
from punt_lux.operations.composition_boundary import CompositionBoundary
from punt_lux.operations.models.common import OpError
from punt_lux.operations.models.scene_results import SceneShown

if TYPE_CHECKING:
    from punt_lux.domain.hub.hub_display import HubDisplay
    from punt_lux.domain.ids import ConnectionId
    from punt_lux.operations.ports import DirtyMarker
    from punt_lux.operations.scene_submission import SceneSubmission

__all__ = ["SceneInstaller"]


@final
class SceneInstaller:
    """Install validated element trees into the store on an owner's behalf."""

    _display: HubDisplay
    _replicator: DirtyMarker
    __slots__ = ("_display", "_replicator")

    def __new__(cls, display: HubDisplay, replicator: DirtyMarker) -> Self:
        self = super().__new__(cls)
        self._display = display
        self._replicator = replicator
        return self

    def install(
        self, submission: SceneSubmission, *, owner: ConnectionId
    ) -> SceneShown | OpError:
        """Install ``submission`` as ``owner``'s scene, or return why it was refused.

        The install and the dirty mark are one step: the Hub writes its own store
        and tells the replicator, which does every send. The store key is never
        the raw ``scene_id``/``frame_id`` the caller submitted — ``.scoped(owner)``
        composes both against ``owner`` here, the one choke point every scene
        install passes through, so two owners' identical raw ids can never
        alias one store key (DES-086). The result still reports the caller's
        own raw name, unchanged — composition is a store-key concern the wire
        contract never surfaces.
        """
        rejection = SubmissionGate().first_rejection(
            submission.scene_id, submission.elements
        )
        if rejection is not None:
            return OpError(code="rejected", reason=rejection)
        scoped = CompositionBoundary.compose_or_reject(lambda: submission.scoped(owner))
        if isinstance(scoped, OpError):
            return scoped
        self._display.show_scene(
            owner,
            scoped.scene_id,
            scoped.elements,
            scoped.presentation,
            ttl_seconds=scoped.ttl_seconds,
        )
        self._replicator.mark_dirty(scoped.scene_id)
        return SceneShown(scene_id=submission.name)
