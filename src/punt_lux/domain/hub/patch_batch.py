"""Typed patch requests parsed from one agent ``update`` call.

:meth:`PatchBatch.from_wire` is the single place the raw ``update`` wire shape
becomes typed domain requests, so the tool and writer never hand-parse it. A
:class:`FieldPatch` carries one element's merged fields.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import starmap
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
    def from_wire(cls, patches: Sequence[object]) -> Self:
        """Split one ``update`` call into typed field-set and removal requests.

        The single wire-boundary parser; every structural rejection — a
        non-mapping entry, a bad ``id``, a malformed ``remove``/``set``, or an id
        both set and removed — raises ``MalformedPatchError``. Same-id sets merge.
        """
        merged: dict[ElementId, dict[str, object]] = {}
        removals: dict[ElementId, None] = {}
        for patch in patches:
            entry = cls._require_mapping(patch)
            element_id = cls._require_id(entry)
            if cls._is_removal(entry, element_id):
                removals[element_id] = None
            else:
                merged.setdefault(element_id, {}).update(
                    cls._require_set(entry, element_id)
                )
        # A set-then-remove of one id would collapse to a bare remove with the
        # entry order lost — the cross-entry form of the within-a-patch exclusivity.
        conflict = next(iter(merged.keys() & removals.keys()), None)
        if conflict is not None:
            raise MalformedPatchError(
                conflict, "id is both set and removed across patch entries"
            )
        return cls(tuple(starmap(FieldPatch, merged.items())), tuple(removals))

    @staticmethod
    def _require_mapping(patch: object) -> Mapping[str, object]:
        """Return the wire entry as a mapping, or raise before any field lookup."""
        if isinstance(patch, Mapping):
            return cast("Mapping[str, object]", patch)
        raise MalformedPatchError(None, f"patch entry must be a mapping, not {patch!r}")

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
        """Return True for a removal, False for a field set; raise on a hybrid.

        A truthy ``remove`` must be exactly boolean ``True`` and carry no ``set``.
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
