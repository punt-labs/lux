"""Field-mutation realizations — the ABC/legacy write seam behind one Protocol.

A field patch is realized differently by the two element models, and the write
path above the seam must not branch on which. An **ABC element** is patched in
place (identity, handlers, observers survive); a **legacy** frozen value is
realized by :func:`dataclasses.replace` and its store index entry rebound to the
fresh instance. Both satisfy one :class:`FieldRealization` contract — rank a
candidate, commit atomically, restore on a mid-batch failure — so the writer
stages, validates, and commits a mixed batch through a single uniform loop.

Legacy replacement shares untouched fields and children by reference. For a
scalar/leaf field that is lossless — a legacy composite's descendants are frozen
values with no live wiring to drop. Child-bearing fields (``children``/``pages``)
are refused before the seam and deferred to ``show``.
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


@final
class LegacyFieldRealization:
    """Realize a field patch on a legacy root by ``replace`` + index rebind.

    A frozen wire dataclass cannot be mutated in place, so the mutation is a fresh
    :func:`dataclasses.replace` instance that shares the other fields and children
    by reference and overrides only the addressed field. Identity is preserved —
    the replacement carries the same ``id`` — and the store's index entry is
    rebound to it, so owners, child-edges, and the root-marker survive untouched.

    Only a legacy *root* reaches this realization; a nested legacy element is
    rejected before the seam (see :mod:`punt_lux.domain.hub.deferral_errors`).
    """

    _index: ElementIndex
    _scene_id: SceneId
    _element_id: ElementId
    _original: WireElement
    _fields: Mapping[str, object]
    # PY-TS-14: memoization cache — ``None`` until realized, so rejection() and
    # commit() share the one ``replace()`` result (the exact instance installed).
    _realized: WireElement | None
    __slots__ = (
        "_element_id",
        "_fields",
        "_index",
        "_original",
        "_realized",
        "_scene_id",
    )

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
        self._realized = None
        return self

    def rejection(self) -> WriteRejected | None:
        """Return why these fields may not be written to the root, or ``None``.

        An unknown field is rejected with the same shape the ABC path uses. The
        candidate is validated (and per-kind coerced) by the same hierarchy walk
        ``show`` uses. Building or validating it raises only agent-facing
        ``ValueError``/``TypeError`` here; any other exception is a bug and propagates.
        """
        known = {field.name for field in dataclass_fields(cast("Any", self._original))}
        for key in self._fields:
            if key not in known:
                return WriteRejected(
                    f"cannot set unknown field {key!r} on element "
                    f"{str(self._element_id)!r}"
                )
        try:
            report = ElementTreeValidator().validate_tree([self._candidate()])
        except (ValueError, TypeError) as exc:
            return WriteRejected(str(exc))
        return None if report.ok else WriteRejected(report.describe())

    def commit(self) -> None:
        """Rebind the root's index entry to the ``replace``-derived instance.

        ``install_root`` re-points an already-installed root's id, leaving the
        root-marker and every id-keyed collaborator unchanged.
        """
        self._index.install_root(self._scene_id, self._element_id, self._candidate())

    def restore(self) -> None:
        """Rebind the root's index entry back to the original frozen instance."""
        self._index.install_root(self._scene_id, self._element_id, self._original)

    def _candidate(self) -> WireElement:
        """Return the fresh frozen instance with the addressed field replaced.

        Realized once and memoized, so ``replace`` runs a single time and commit
        installs the exact instance rejection validated. The casts record the
        frozen-wire shape ``replace`` needs but the ``Element`` Protocol omits.
        """
        if self._realized is None:
            fresh = replace(cast("Any", self._original), **dict(self._fields))
            self._realized = cast("WireElement", fresh)
        return self._realized
