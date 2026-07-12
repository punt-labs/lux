"""Typed rejections for the agent ``update`` write path.

Two distinct agent errors the writer raises and converts to a
:class:`WriteRejected`: a wire patch that is structurally malformed
(:class:`MalformedPatchError`) and a patch aimed at an element that carries no
mutable setter surface (:class:`NotPatchableError`). Both are narrow on purpose:
catching them — rather than a broad ``TypeError`` — keeps an incidental bug in a
setter from being laundered into an agent-facing "reason".
"""

from __future__ import annotations

from dataclasses import dataclass

from punt_lux.domain.ids import ElementId, SceneId

__all__ = ["MalformedPatchError", "NotPatchableError"]


@dataclass(frozen=True, slots=True)
class MalformedPatchError(ValueError):
    """Raised when a raw ``update`` patch dict is structurally invalid.

    A patch must carry an ``id`` and be either a truthy ``remove`` or a ``set``
    mapping. ``element_id`` is the offending patch's id, or ``None`` when the
    ``id`` itself is missing.
    """

    # PY-TS-14: absence is the documented state — a patch missing its ``id`` has
    # no element to name, so the reason stands alone.
    element_id: ElementId | None
    detail: str

    def __str__(self) -> str:
        if self.element_id is None:
            return self.detail
        return f"{self.detail} (element {str(self.element_id)!r})"


@dataclass(frozen=True, slots=True)
class NotPatchableError(TypeError):
    """Raised when a patch targets an element with no mutable setter surface.

    Only migrated ABC elements accept field patches; a legacy wire dataclass is
    frozen and carries no ``_set_<field>`` setters, so a patch against one is a
    clean agent-facing rejection, not an internal error.
    """

    scene_id: SceneId
    element_id: ElementId

    def __str__(self) -> str:
        return (
            f"element {str(self.element_id)!r} in scene {str(self.scene_id)!r} "
            f"is not patchable"
        )
