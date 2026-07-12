"""Typed rejections for the agent ``update`` write path.

Three agent errors the writer raises and converts to a
:class:`~punt_lux.domain.hub.write_result.WriteRejected`:

- :class:`MalformedPatchError` — a wire patch that is structurally invalid.
- :class:`ImmutableFieldError` — a patch targeting ``id`` or ``kind``, which no
  write may change for either element model.
- :class:`NestedLegacyWriteError` — a patch or removal addressed to a legacy
  element nested below a legacy composite, which the write path defers to
  ``show`` (whole-tree resend) rather than rebuilding the frozen spine.

All three are narrow on purpose: catching them — rather than a broad exception —
keeps an incidental internal fault from being laundered into an agent-facing
"reason".
"""

from __future__ import annotations

from dataclasses import dataclass

from punt_lux.domain.ids import ElementId, SceneId

__all__ = ["ImmutableFieldError", "MalformedPatchError", "NestedLegacyWriteError"]


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
class ImmutableFieldError(ValueError):
    """Raised when a ``set`` targets an immutable field (``id`` or ``kind``).

    An element's identity is its ``id`` plus its fields, and its ``kind`` is the
    type discriminator that selects its renderer and contract. Changing either is
    a remove-and-add, not a field patch, so both are refused before any mutation,
    uniformly across the ABC and legacy element models.
    """

    element_id: ElementId
    field: str

    def __str__(self) -> str:
        return (
            f"cannot set immutable field {self.field!r} on element "
            f"{str(self.element_id)!r}; {self.field} is fixed at install"
        )


@dataclass(frozen=True, slots=True)
class NestedLegacyWriteError(TypeError):
    """Raised when a write addresses a legacy element below a legacy composite.

    A legacy root is written by ``dataclasses.replace`` and its index rebound,
    but a legacy element nested below a legacy composite would leave the frozen
    parent holding the stale child by reference. Rebuilding the spine is
    deliberately not built for the mixed migration period; the client resends the
    amended tree via ``show`` instead. The rejection names the enclosing root's
    kind and self-deletes once that container migrates to the ABC path.
    """

    scene_id: SceneId
    element_id: ElementId
    root_kind: str

    def __str__(self) -> str:
        return (
            f"cannot write legacy element {str(self.element_id)!r} nested below "
            f"a legacy {self.root_kind!r}; resend the whole tree via show"
        )
