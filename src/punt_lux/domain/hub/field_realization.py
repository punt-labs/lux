"""Field-mutation realization behind the ``FieldRealization`` Protocol.

A field patch on an ABC element is realized in place: identity, handlers, and
observers survive the mutation. The realization stages the patch — rank a
candidate, commit atomically, restore on a mid-batch failure — so the writer
stages, validates, and commits a batch through a single uniform loop.

Child-bearing fields (``children`` / ``tabs``) are refused before the seam and
deferred to ``show``.
"""

from __future__ import annotations

from copy import deepcopy
from typing import (
    TYPE_CHECKING,
    Protocol,
    Self,
    final,
)

from punt_lux.domain.element_abc import Element as AbcElement
from punt_lux.domain.hub.write_result import WriteRejected
from punt_lux.domain.validation import ValidationReport

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ["AbcFieldRealization", "FieldRealization"]


class FieldRealization(Protocol):
    """A staged field mutation: rank a candidate, commit, or restore.

    The writer treats every target uniformly through this contract, never learning
    whether an element is ABC or legacy. ``rejection`` decides the batch before any
    ``commit`` runs; ``restore`` undoes a commit when a later target fails.
    """

    def rejection(self) -> WriteRejected | None:
        """Return why the patch may not be written, or ``None`` if it may."""
        ...

    def commit(self) -> None:
        """Apply the mutation, snapshotting enough to restore it exactly."""
        ...

    def restore(self) -> None:
        """Undo a committed mutation, returning the store to its prior state."""
        ...


@final
class AbcFieldRealization:
    """Realize a field patch on an ABC element by in-place ``apply_patch``.

    The object *is* the identity, so mutating it in place preserves its handlers
    and observers and the change is visible through any parent that holds it.
    Validation runs on a throwaway deep copy so a rejected write never touches it.
    """

    _element: AbcElement
    _fields: Mapping[str, object]
    _snapshot: dict[str, object]
    __slots__ = ("_element", "_fields", "_snapshot")

    def __new__(cls, element: AbcElement, fields: Mapping[str, object]) -> Self:
        self = super().__new__(cls)
        self._element = element
        self._fields = fields
        self._snapshot = {}
        return self

    def rejection(self) -> WriteRejected | None:
        """Return why these fields may not be written to the element, or ``None``.

        An unknown field (no ``_set_<field>`` setter), a setter that refuses a bad
        value, and a self-validation failure all surface here as the agent-facing
        reason; any other exception is an internal bug and propagates.
        """
        for key in self._fields:
            if not callable(getattr(self._element, f"_set_{key}", None)):
                return WriteRejected(
                    f"cannot set unknown field {key!r} on element {self._element.id!r}"
                )
        try:
            errors = deepcopy(self._element).apply_patch(self._fields).validate()
        except (ValueError, TypeError) as exc:
            return WriteRejected(str(exc))
        return WriteRejected(ValidationReport(errors).describe()) if errors else None

    def commit(self) -> None:
        """Snapshot the element's field state, then patch it in place."""
        self._snapshot = dict(vars(self._element))
        self._element.apply_patch(self._fields)

    def restore(self) -> None:
        """Roll the element back to its pre-commit field state."""
        vars(self._element).clear()
        vars(self._element).update(self._snapshot)
