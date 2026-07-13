"""Typed patch requests parsed from one agent ``update`` call.

:meth:`PatchBatch.from_wire` is the single place the raw ``update`` wire shape
becomes typed domain requests, so the tool and writer never hand-parse it. A
:class:`FieldPatch` carries one element's merged fields.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Self, cast

from punt_lux.domain.hub.write_errors import MalformedPatchError
from punt_lux.domain.ids import ElementId

__all__ = ["FieldPatch", "PatchBatch"]


@dataclass(frozen=True, slots=True)
class FieldPatch:
    """The merged fields to write onto one element in an ``update`` batch."""

    element_id: ElementId
    # PY-TS-14: wire boundary — JSON object values arrive as ``object`` and are
    # coerced by each element's setter / validation walk, so the type stays open.
    fields: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class PatchBatch:
    """One ``update`` call split into its field-set and removal requests."""

    field_patches: tuple[FieldPatch, ...]
    removals: tuple[ElementId, ...]

    @classmethod
    def from_wire(cls, patches: Sequence[Mapping[str, object]]) -> Self:
        """Build a batch from the ``update`` tool's raw patch dicts.

        Each patch is an ``id`` plus exactly one of two mutually exclusive shapes —
        a boolean-``True`` ``remove`` or a ``set`` mapping. Both in one patch, a
        non-boolean ``remove``, neither, or an id set in one entry and removed in
        another all raise ``MalformedPatchError``; same-id sets merge in order.
        """
        merged: dict[ElementId, dict[str, object]] = {}
        removals: dict[ElementId, None] = {}
        for patch in patches:
            element_id = cls._require_id(patch)
            if cls._is_removal(patch, element_id):
                removals[element_id] = None
            else:
                merged.setdefault(element_id, {}).update(
                    cls._require_set(patch, element_id)
                )
        # A set-then-remove of one id would collapse to a bare remove with the
        # entry order lost — the cross-entry form of the within-a-patch exclusivity.
        conflict = next(iter(merged.keys() & removals.keys()), None)
        if conflict is not None:
            raise MalformedPatchError(
                conflict, "id is both set and removed across patch entries"
            )
        return cls(cls._field_patches(merged), tuple(removals))

    @staticmethod
    def _field_patches(
        merged: Mapping[ElementId, Mapping[str, object]],
    ) -> tuple[FieldPatch, ...]:
        """Freeze the merged per-id field maps into ordered ``FieldPatch`` values."""
        return tuple(FieldPatch(eid, fields) for eid, fields in merged.items())

    @staticmethod
    def _require_id(patch: Mapping[str, object]) -> ElementId:
        """Return the patch's ``id``, or raise if it is not a non-empty string."""
        raw = patch.get("id")
        if not isinstance(raw, str) or not raw:
            raise MalformedPatchError(
                None, f"patch 'id' must be a non-empty string, not {raw!r}"
            )
        return ElementId(raw)

    @staticmethod
    def _is_removal(patch: Mapping[str, object], element_id: ElementId) -> bool:
        """Return True for a well-formed removal, False for a field set.

        A falsy or absent ``remove`` is a field set. A truthy ``remove`` must be
        exactly boolean ``True`` and carry no ``set``; any other combination raises.
        """
        remove = patch.get("remove", False)
        if not remove:
            return False
        if remove is not True:
            raise MalformedPatchError(
                element_id, f"'remove' must be the boolean true, not {remove!r}"
            )
        if patch.get("set") is not None:
            raise MalformedPatchError(
                element_id,
                "patch specifies both a truthy 'remove' and a 'set'; "
                "they are mutually exclusive",
            )
        return True

    @staticmethod
    def _require_set(
        patch: Mapping[str, object], element_id: ElementId
    ) -> Mapping[str, object]:
        """Return the patch's ``set`` mapping or raise on a non-mapping value."""
        fields = patch.get("set")
        if not isinstance(fields, Mapping):
            raise MalformedPatchError(
                element_id,
                "patch carries neither a truthy 'remove' nor a 'set' mapping",
            )
        return cast("Mapping[str, object]", fields)
