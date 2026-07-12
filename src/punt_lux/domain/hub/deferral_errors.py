"""Write rejections that direct the client to resend the whole tree via ``show``.

Two writes the narrow ``update`` path cannot realize authoritatively during the
mixed-migration period, each answered by the always-correct whole-tree resend:

- :class:`NestedLegacyWriteError` — a patch or removal addressed to a legacy
  element nested below a legacy composite. Rebuilding the frozen spine is
  deliberately not built for the mixed period.
- :class:`StructuralFieldWriteError` — a ``set`` whose field carries child
  elements (``children`` / ``pages`` on a legacy composite). The value-replacement
  seam realizes only scalar/leaf fields; installing a new child set would need a
  subtree reinstall the narrow path does not perform.

Both are ``TypeError`` deferrals, distinct from the hard field-constraint
rejections in :mod:`punt_lux.domain.hub.write_errors`: a deferral is not "you may
not", it is "not through this door — use ``show``". Each self-deletes as its
container kind migrates to the Element-ABC path.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from punt_lux.domain.ids import ElementId, SceneId

__all__ = ["NestedLegacyWriteError", "StructuralFieldWriteError"]


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


@dataclass(frozen=True, slots=True)
class StructuralFieldWriteError(TypeError):
    """Raised when a ``set`` names a field that carries child elements.

    ``children`` and ``pages`` on a legacy composite hold Elements, not scalars.
    The value-replacement seam rebinds only the addressed root's index entry; it
    installs no new children (no index, owner, or child-edge is created) and
    evicts no old ones. Accepting such a patch would render a new child set the
    Hub index does not know — a click on a new child would resolve to nothing and
    the old children would linger. So a structural field is refused before any
    mutation, uniformly for both element models, and the client resends the whole
    tree via ``show`` where install rebuilds the subtree correctly.
    """

    element_id: ElementId
    field: Literal["children", "pages"]

    def __str__(self) -> str:
        return (
            f"cannot set structural field {self.field!r} on element "
            f"{str(self.element_id)!r} via update; it carries child elements — "
            f"resend the whole tree via show"
        )
