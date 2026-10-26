"""Hard field-constraint rejections for the agent ``update`` write path.

Two agent errors the writer raises and converts to a
:class:`~punt_lux.domain.hub.write_result.WriteRejected`:

- :class:`MalformedPatchError` — a wire patch that is structurally invalid.
- :class:`ImmutableFieldError` — a patch targeting ``id`` or ``kind``, which no
  write may change for either element model.

Both are narrow on purpose: catching them — rather than a broad exception — keeps
an incidental internal fault from being laundered into an agent-facing "reason".
Deferrals that point the client at ``show`` (nested-legacy, structural-field)
live in :mod:`punt_lux.domain.hub.deferral_errors`; these two are outright "no".
"""

from __future__ import annotations

from typing import Literal, Self

from punt_lux.domain.ids import ElementId

__all__ = ["ImmutableFieldError", "MalformedPatchError"]


class MalformedPatchError(ValueError):
    """Raised when a raw ``update`` patch dict is structurally invalid.

    A patch must carry an ``id`` and be either a truthy ``remove`` or a ``set``
    mapping. ``element_id`` is the offending patch's id, or ``None`` when the
    ``id`` itself is missing.
    """

    # PY-TS-14: absence is the documented state — a patch missing its ``id`` has
    # no element to name, so the reason stands alone.
    _element_id: ElementId | None
    _detail: str

    def __new__(cls, element_id: ElementId | None, detail: str) -> Self:
        self = super().__new__(cls, element_id, detail)
        self._element_id = element_id
        self._detail = detail
        return self

    @property
    def element_id(self) -> ElementId | None:
        """The offending patch's id; ``None`` when the patch has none."""
        return self._element_id

    @property
    def detail(self) -> str:
        """What is wrong with the patch."""
        return self._detail

    def __str__(self) -> str:
        return (
            self._detail
            if self._element_id is None
            else f"{self._detail} (element {str(self._element_id)!r})"
        )


class ImmutableFieldError(ValueError):
    """Raised when a ``set`` targets an immutable field (``id`` or ``kind``).

    An element's identity is its ``id`` plus its fields, and its ``kind`` is the
    type discriminator that selects its renderer and contract. Changing either is
    a remove-and-add, not a field patch, so both are refused before any mutation,
    uniformly across the ABC and legacy element models.
    """

    _element_id: ElementId
    _field: Literal["id", "kind"]

    def __new__(cls, element_id: ElementId, field: Literal["id", "kind"]) -> Self:
        self = super().__new__(cls, element_id, field)
        self._element_id = element_id
        self._field = field
        return self

    @property
    def element_id(self) -> ElementId:
        """The element the write named."""
        return self._element_id

    @property
    def field(self) -> Literal["id", "kind"]:
        """The immutable field the write named."""
        return self._field

    def __str__(self) -> str:
        return (
            f"cannot set immutable field {self._field!r} on element "
            f"{str(self._element_id)!r}; {self._field} is fixed at install"
        )
