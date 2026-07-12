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

from typing import TYPE_CHECKING, Literal, cast, final

from punt_lux.domain.hub.deferral_errors import StructuralFieldWriteError
from punt_lux.domain.hub.write_errors import ImmutableFieldError

if TYPE_CHECKING:
    from collections.abc import Mapping

    from punt_lux.domain.ids import ElementId

__all__ = ["FieldGate"]

_IMMUTABLE_FIELDS = frozenset({"id", "kind"})
# Complete and closed: window/modal carry children, paged carries pages, tab_bar
# carries tabs; tree's ``nodes`` is plain data, never index-installed. Migration
# only removes legacy kinds, so no new structural field can ever join this set.
_STRUCTURAL_FIELDS = frozenset({"children", "pages", "tabs"})


@final
class FieldGate:
    """Reject a field patch that names an immutable or a structural field."""

    __slots__ = ()

    @staticmethod
    def reject(element_id: ElementId, fields: Mapping[str, object]) -> None:
        """Raise the matching typed error if ``fields`` names a forbidden field.

        Each intersection proves the field is a declared literal for the error.
        """
        keys = fields.keys()
        if immutable := _IMMUTABLE_FIELDS & keys:
            raise ImmutableFieldError(
                element_id=element_id,
                field=cast("Literal['id', 'kind']", next(iter(immutable))),
            )
        if structural := _STRUCTURAL_FIELDS & keys:
            raise StructuralFieldWriteError(
                element_id=element_id,
                field=cast(
                    "Literal['children', 'pages', 'tabs']", next(iter(structural))
                ),
            )
