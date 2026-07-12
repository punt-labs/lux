"""Field-mutation realizations — the ABC/legacy write seam behind one Protocol.

A field patch is realized differently by the two element models, and the write
path above the seam must not branch on which. An **ABC element** is patched in
place (its identity, handlers, and observers survive); a **legacy** frozen value
is realized by :func:`dataclasses.replace`, sharing its untouched fields and
children by reference, and its store index entry is rebound to the fresh
instance. Both realizations satisfy one :class:`FieldRealization` contract —
report a rejection against a candidate, commit atomically, restore on a
mid-batch failure — so the writer stages, validates, and commits a mixed batch
through a single uniform loop.

Because migration admits no mixed composites (an ABC composite's descendants are
all ABC; a legacy composite's descendants are all frozen values), sharing a
legacy composite's children by reference is unconditionally lossless: there is
no live wiring on a legacy child to drop.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import fields as dataclass_fields, replace
from typing import (
    TYPE_CHECKING,
    Protocol,
    Self,
    cast,
    final,
    runtime_checkable,
)

from punt_lux.domain.element_abc import Element as AbcElement
from punt_lux.domain.hub.write_result import WriteRejected
from punt_lux.domain.validation import ValidationReport
from punt_lux.domain.validation_walk import ElementTreeValidator

if TYPE_CHECKING:
    from collections.abc import Mapping
    from typing import Any

    from punt_lux.domain.element import Element as WireElement
    from punt_lux.domain.hub.element_index import ElementIndex
    from punt_lux.domain.ids import ElementId, SceneId

__all__ = ["AbcFieldRealization", "FieldRealization", "LegacyFieldRealization"]


@runtime_checkable
class FieldRealization(Protocol):
    """A staged field mutation: rank a candidate, commit, or restore.

    The writer treats every target uniformly through this contract — it never
    learns whether an element is ABC or legacy. ``rejection`` decides the batch
    before any ``commit`` runs; ``restore`` undoes a committed mutation exactly
    when a later target in the same batch fails to commit.
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

    The object *is* the identity, so mutating it in place preserves its handler
    registrations and property observers, and the change is visible through any
    parent composite that holds the same object. Validation runs on a throwaway
    deep copy so a rejected write never touches the live element.
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

        An unknown field (no ``_set_<field>`` setter) is an agent error reported
        cleanly. A setter that refuses a bad value (``TypeError`` / ``ValueError``)
        and a self-validation failure both surface here as the agent-facing
        reason; any other exception is an internal bug in a setter and propagates.
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
        if errors:
            return WriteRejected(ValidationReport(errors).describe())
        return None

    def commit(self) -> None:
        """Snapshot the element's field state, then patch it in place."""
        self._snapshot = dict(vars(self._element))
        self._element.apply_patch(self._fields)

    def restore(self) -> None:
        """Roll the element back to its pre-commit field state."""
        vars(self._element).clear()
        vars(self._element).update(self._snapshot)


@final
class LegacyFieldRealization:
    """Realize a field patch on a legacy root by ``replace`` + index rebind.

    A frozen wire dataclass cannot be mutated in place, so the mutation is a
    fresh instance from :func:`dataclasses.replace` that shares the element's
    other fields and children by reference and overrides only the addressed
    field. Identity is preserved because a value object's identity is its ``id``
    and fields and the replacement carries the same ``id``; the store's index
    entry is rebound to the fresh instance so owners, child-edges, and the
    root-marker — all keyed by id — survive untouched.

    Only a legacy *root* reaches this realization; a nested legacy element is
    rejected before the seam with a ``NestedLegacyWriteError`` (see
    :mod:`punt_lux.domain.hub.write_errors`).
    """

    _index: ElementIndex
    _scene_id: SceneId
    _element_id: ElementId
    _original: WireElement
    _fields: Mapping[str, object]
    __slots__ = ("_element_id", "_fields", "_index", "_original", "_scene_id")

    def __new__(
        cls,
        index: ElementIndex,
        scene_id: SceneId,
        element_id: ElementId,
        original: WireElement,
        fields: Mapping[str, object],
    ) -> Self:
        self = super().__new__(cls)
        self._index = index
        self._scene_id = scene_id
        self._element_id = element_id
        self._original = original
        self._fields = fields
        return self

    def rejection(self) -> WriteRejected | None:
        """Return why these fields may not be written to the root, or ``None``.

        An unknown field (not a dataclass field of the frozen value) is rejected
        with the same shape the ABC path uses, so the two models reject an
        unknown field uniformly. The candidate is validated by the same
        hierarchy walk ``show`` uses, which also coerces per-kind values — so no
        codec round-trip is needed to validate the replacement.
        """
        known = {field.name for field in dataclass_fields(cast("Any", self._original))}
        for key in self._fields:
            if key not in known:
                return WriteRejected(
                    f"cannot set unknown field {key!r} on element "
                    f"{str(self._element_id)!r}"
                )
        report = ElementTreeValidator().validate_tree([self._candidate()])
        if not report.ok:
            return WriteRejected(report.describe())
        return None

    def commit(self) -> None:
        """Rebind the root's index entry to the ``replace``-derived instance.

        ``install_root`` re-points the index entry for an id already installed
        as a root, so it doubles as the rebind — the root-marker and every
        id-keyed collaborator are unchanged.
        """
        self._index.install_root(self._scene_id, self._element_id, self._candidate())

    def restore(self) -> None:
        """Rebind the root's index entry back to the original frozen instance."""
        self._index.install_root(self._scene_id, self._element_id, self._original)

    def _candidate(self) -> WireElement:
        """Return the fresh frozen instance with the addressed field replaced.

        The casts record that the legacy seam guarantees a frozen wire dataclass
        — the shape :func:`dataclasses.replace` requires and returns but the
        structural ``Element`` Protocol does not encode.
        """
        fresh = replace(cast("Any", self._original), **dict(self._fields))
        return cast("WireElement", fresh)
