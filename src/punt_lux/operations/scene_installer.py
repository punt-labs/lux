"""SceneInstaller — validate a built element tree, install it, mark it for resend.

The one install: every scene reaches ``HubDisplay`` through here, whether a
client submitted it over the wire or the Hub constructed it itself (target.md —
the Hub decodes *or constructs* UI). It runs the submission gate first, so a
tree with any invalid element is refused whole and nothing partial is installed.

Installing registers nobody: the owner is attribution, not contact, so an install
never recreates a session its client's departure removed.
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

        The install and the dirty mark are one step. The store key is never the
        raw id the caller submitted: ``.scoped(owner)`` composes scene and frame
        ids against ``owner`` here, so two owners' identical raw ids can never
        alias one store key. The result still reports the caller's own raw name.
        """
        rejection = SubmissionGate().first_rejection(
            submission.scene_id, submission.elements
        )
        if rejection is not None:
            return OpError(code="rejected", reason=rejection)
        scoped = CompositionBoundary.compose_or_reject(lambda: submission.scoped(owner))
        if isinstance(scoped, OpError):
            return scoped
        left = self._display.frames.presentation_for(scoped.scene_id).frame_id
        self._display.show_scene(
            owner,
            scoped.scene_id,
            scoped.elements,
            scoped.presentation,
            ttl_seconds=scoped.ttl_seconds,
        )
        self._replicator.mark_dirty(scoped.scene_id)
        self._resend_survivors(left, scoped.presentation.frame_id)
        return SceneShown(scene_id=submission.name)

    def _resend_survivors(self, left: str, entered: str) -> None:
        """Resend what a move out of ``left`` leaves, for the new canonical owner."""
        survivors = (
            self._display.frames.scenes_in_frame(left) if left != entered else ()
        )
        for survivor in survivors:
            self._replicator.mark_dirty(survivor)
