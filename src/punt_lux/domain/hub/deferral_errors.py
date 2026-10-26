"""Write rejection that directs the client to resend the whole tree via ``show``.

A ``set`` whose field carries child elements cannot be realized by the narrow
``update`` path, and is answered by the always-correct whole-tree resend. It is a
``TypeError`` deferral, distinct from the hard field-constraint rejections in
:mod:`punt_lux.domain.hub.write_errors`: not "you may not", but "not through this
door — use ``show``".
"""

from __future__ import annotations

from typing import Literal, Self

from punt_lux.domain.ids import ElementId

__all__ = ["StructuralFieldWriteError"]


class StructuralFieldWriteError(TypeError):
    """Raised when a ``set`` names a field that carries child elements.

    ``children`` and ``tabs`` on a composite hold Elements, not scalars. The
    value-replacement seam rebinds only the addressed element in place; it
    installs no new children (no index, owner, or child-edge is created) and
    evicts no old ones. Accepting such a patch would render a new child set the
    Hub index does not know — a click on a new child would resolve to nothing and
    the old children would linger. So a structural field is refused before any
    mutation, and the client resends the whole tree via ``show`` where install
    rebuilds the subtree correctly.
    """

    _element_id: ElementId
    _field: Literal["children", "tabs"]

    def __new__(cls, element_id: ElementId, field: Literal["children", "tabs"]) -> Self:
        self = super().__new__(cls, element_id, field)
        self._element_id = element_id
        self._field = field
        return self

    @property
    def element_id(self) -> ElementId:
        """The element the write named."""
        return self._element_id

    @property
    def field(self) -> Literal["children", "tabs"]:
        """The structural field the write named."""
        return self._field

    def __str__(self) -> str:
        return (
            f"cannot set structural field {self._field!r} on element "
            f"{str(self._element_id)!r} via update; it carries child elements — "
            f"resend the whole tree via show"
        )
