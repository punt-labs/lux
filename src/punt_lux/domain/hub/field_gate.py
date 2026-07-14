"""FieldGate — refuse a field patch that names a forbidden field, before dispatch.

Two field-name classes may never be written through the narrow ``update`` path,
uniformly for both element models, so the gate runs ahead of the ABC/legacy seam:

- **Immutable** (``id``/``kind``): changing either is a remove-and-add — ``id`` is
  the store index key, ``kind`` selects the renderer.
- **Structural** (``children``/``pages``/``tabs``): these carry child Elements. The
  value-replacement seam rebinds only the root's index entry, so such a write
  defers to ``show`` — which reinstalls the subtree — rather than desyncing it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, final

from punt_lux.domain.hub.deferral_errors import StructuralFieldWriteError
from punt_lux.domain.hub.write_errors import ImmutableFieldError

if TYPE_CHECKING:
    from collections.abc import Mapping

    from punt_lux.domain.ids import ElementId

__all__ = ["FieldGate"]

_IMMUTABLE_FIELDS = frozenset({"id", "kind"})
# A patch naming several forbidden fields is rejected on a fixed precedence — id,
# then kind, then children, pages, tabs — so the reported field never varies across
# runs. Both sets are closed: migration only removes legacy kinds, none can join.
_STRUCTURAL_FIELDS = frozenset({"children", "pages", "tabs"})


@final
class FieldGate:
    """Reject a field patch that names an immutable or a structural field."""

    __slots__ = ()

    @staticmethod
    def reject(element_id: ElementId, fields: Mapping[str, object]) -> None:
        """Raise the matching typed error if ``fields`` names a forbidden field."""
        keys = fields.keys()
        if _IMMUTABLE_FIELDS & keys:
            immutable: Literal["id", "kind"] = "id" if "id" in keys else "kind"
            raise ImmutableFieldError(element_id=element_id, field=immutable)
        if _STRUCTURAL_FIELDS & keys:
            structural: Literal["children", "pages", "tabs"] = (
                "children"
                if "children" in keys
                else "pages"
                if "pages" in keys
                else "tabs"
            )
            raise StructuralFieldWriteError(element_id=element_id, field=structural)
