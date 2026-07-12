"""FieldGate — refuse a field patch that names a forbidden field, before dispatch.

Two field-name classes may never be written through the narrow ``update`` path,
uniformly for both element models:

- **Immutable** (``id``/``kind``): changing either is a remove-and-add, not a
  field patch — ``id`` is the store index key, ``kind`` selects the renderer.
- **Structural** (``children``/``pages``): these carry child Elements. The
  value-replacement seam rebinds only the addressed root's index entry, so it can
  install no new children and evict no old ones; such a write defers to ``show``,
  which rebuilds the subtree correctly, rather than desyncing the Hub index from
  the rendered tree.

The gate runs ahead of the ABC/legacy seam so both models reject the same fields
for the same reason.
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
_STRUCTURAL_FIELDS = frozenset({"children", "pages"})


@final
class FieldGate:
    """Reject a field patch that names an immutable or a structural field."""

    __slots__ = ()

    @staticmethod
    def reject(element_id: ElementId, fields: Mapping[str, object]) -> None:
        """Raise the matching typed error if ``fields`` names a forbidden field.

        The intersections prove the named field is one of the declared literals, so
        the typed error carries a ``Literal`` field rather than an open ``str``.
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
                field=cast("Literal['children', 'pages']", next(iter(structural))),
            )
