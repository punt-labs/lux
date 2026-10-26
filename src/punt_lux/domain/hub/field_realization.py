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
    cast,
    final,
)

from punt_lux.domain.element_abc import Element as AbcElement
from punt_lux.domain.hub.write_result import WriteRejected
from punt_lux.domain.nesting_cap import NestingCap
from punt_lux.domain.validation import ValidationReport

if TYPE_CHECKING:
    from collections.abc import Mapping

    from punt_lux.domain.element import Element as WireElement

__all__ = ["AbcFieldRealization", "FieldRealization"]


class FieldRealization(Protocol):
    """A staged field mutation: rank a candidate, commit, or restore.

    The writer treats every target uniformly through this contract:
    ``rejection`` decides the batch before any ``commit`` runs; ``restore``
    undoes a commit when a later target fails.
    """

    def rejection(self) -> WriteRejected | None:
        """Return why the patch may not be written, or ``None`` if it may."""
        ...

    def current(self) -> WireElement:
        """The target as the store holds it now."""
        ...

    def projected(self) -> tuple[str, WireElement]:
        """The target's id and the element it would become, without applying it."""
        ...

    def write(self) -> tuple[AbcElement, Mapping[str, object]]:
        """The element this realization patches and the very mapping it patches with."""
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
    Validation, and the check that the scene would not nest too deeply, run on a
    throwaway deep copy so a rejected write never touches the element, and no
    observer hears of it.
    """

    _element: AbcElement
    _fields: Mapping[str, object]
    _snapshot: dict[str, object]
    _patched: AbcElement | None
    __slots__ = ("_element", "_fields", "_patched", "_snapshot")

    def __new__(cls, element: AbcElement, fields: Mapping[str, object]) -> Self:
        self = super().__new__(cls)
        self._element = element
        self._fields = fields
        self._snapshot = {}
        self._patched = None  # PY-TS-14 OK: absent until first asked for
        return self

    def rejection(self) -> WriteRejected | None:
        """Return why these fields may not be written to the element, or ``None``.

        An unknown field (no ``_set_<field>`` setter), a setter that refuses a bad
        value, and a self-validation failure all surface here as the agent-facing
        reason; any other exception is an internal bug and propagates.
        """
        return self._unknown_field() or self._invalid_once_patched()

    def _unknown_field(self) -> WriteRejected | None:
        for key in self._fields:
            if not callable(getattr(self._element, f"_set_{key}", None)):
                return WriteRejected(
                    f"cannot set unknown field {key!r} on element {self._element.id!r}"
                )
        return None

    def _invalid_once_patched(self) -> WriteRejected | None:
        try:
            errors = self._patched_copy().validate()
        except (ValueError, TypeError) as exc:
            return WriteRejected(str(exc))
        except RecursionError:  # a form too deep to even build is past the cap
            return WriteRejected(NestingCap.reason())
        return WriteRejected(ValidationReport(errors).describe()) if errors else None

    def current(self) -> WireElement:
        """The element as the store holds it, untouched."""
        return self._wire(self._element)

    def projected(self) -> tuple[str, WireElement]:
        """The element's id and what it would be once the patch is applied.

        A throwaway deep copy, made once and shared with ``rejection``: the element
        itself, and any observer of it, is untouched.
        """
        return self._element.id, self._wire(self._patched_copy())

    def write(self) -> tuple[AbcElement, Mapping[str, object]]:
        """The element and the mapping ``commit`` hands its ``apply_patch``."""
        return self._element, self._fields

    @staticmethod
    def _wire(element: AbcElement) -> WireElement:
        """The ABC element seen through its wire contract.

        Every ABC kind the store holds has a wire form (``to_dict``); the ABC base
        leaves it to the kind, so a kind without one fails loudly where the cap
        asks for it, never passes unmeasured.
        """
        return cast("WireElement", element)

    def _patched_copy(self) -> AbcElement:
        if self._patched is None:
            self._patched = deepcopy(self._element).apply_patch(self._fields)
        return self._patched

    def commit(self) -> None:
        """Snapshot the element's field state, then patch it in place."""
        self._snapshot = dict(vars(self._element))
        self._element.apply_patch(self._fields)

    def restore(self) -> None:
        """Roll the element back to its pre-commit field state."""
        vars(self._element).clear()
        vars(self._element).update(self._snapshot)
