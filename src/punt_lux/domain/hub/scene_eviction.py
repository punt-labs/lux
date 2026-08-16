"""SceneEviction — tear a scene's roots down and lift its quarantine as one step.

Wraps :class:`~punt_lux.domain.hub.subtree_remover.SubtreeRemover`'s
``drop_scene_roots`` with a matching quarantine lift, so every path that
removes a scene's roots — a wholesale ``replace_scene``, a user closing its
frame, a frame's TTL expiring — leaves no orphan quarantine record on a
scene that no longer exists. A later write against that (gone) scene reports
"not found", the answer callers expect, rather than a spurious quarantine
rejection.

Satisfies :class:`~punt_lux.domain.hub.frame_lifecycle.SceneRootRemover`
structurally, so ``FrameLifecycle`` reaches through here without knowing
about quarantine at all.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from collections.abc import Callable

    from punt_lux.domain.hub.subtree_remover import SubtreeRemover
    from punt_lux.domain.ids import SceneId

__all__ = ["SceneEviction"]


@final
class SceneEviction:
    """Drop a scene's roots and lift any quarantine on it, in that order.

    The lift callback funnels through
    :meth:`~punt_lux.domain.hub.hub_display.HubDisplay._lift_quarantine`, so
    a teardown-driven clear and an owner-driven empty-scene clear both fire
    the same observer cascade (in particular
    :meth:`CrashAttribution.clear_tally`).
    """

    _remover: SubtreeRemover
    _lift_quarantine: Callable[[SceneId], None]
    __slots__ = ("_lift_quarantine", "_remover")

    def __new__(
        cls,
        remover: SubtreeRemover,
        lift_quarantine: Callable[[SceneId], None],
    ) -> Self:
        self = super().__new__(cls)
        self._remover = remover
        self._lift_quarantine = lift_quarantine
        return self

    def drop_scene_roots(self, scene_id: SceneId) -> None:
        """Drop the scene's roots and lift its quarantine, if any.

        The remover call runs whether or not the scene was quarantined — the
        teardown is unconditional — and the lift is a no-op on a scene with
        no record, so no phantom observer event fires on an already-clean
        scene.
        """
        self._remover.drop_scene_roots(scene_id)
        self._lift_quarantine(scene_id)
