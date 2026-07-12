"""Typed patch requests parsed from one agent ``update`` call.

The ``update`` tool submits a list of raw patch dicts — each an ``id`` plus a
``set`` mapping or a truthy ``remove``. :meth:`PatchBatch.from_wire` is the
single place that wire shape becomes typed domain requests, so the tool layer
and the writer never hand-parse it. A :class:`FieldPatch` is the merged fields
for one element; how a field mutation is *realized* on the stored object belongs
to the write seam, not here.
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
    # coerced by each element's setter / validation walk, so the value type stays
    # open here.
    fields: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class PatchBatch:
    """One ``update`` call split into its field-set and removal requests."""

    field_patches: tuple[FieldPatch, ...]
    removals: tuple[ElementId, ...]

    @classmethod
    def from_wire(cls, patches: Sequence[Mapping[str, object]]) -> Self:
        """Build a batch from the ``update`` tool's raw patch dicts.

        Each patch must carry an ``id`` and be exactly one of two shapes — a
        removal (``remove`` set to the boolean ``True``) or a field set (a
        ``set`` mapping). The two are mutually exclusive; a patch carrying both,
        a non-boolean ``remove`` (``"yes"``, ``1``), or neither is rejected loud
        as a ``MalformedPatchError`` rather than silently dropping the ``set``.
        Field patches on the same id are merged so a duplicate id commits as one
        unit; both maps double as order-preserving de-duplicators for their ids.
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
        field_patches = tuple(FieldPatch(eid, fields) for eid, fields in merged.items())
        return cls(field_patches, tuple(removals))

    @staticmethod
    def _require_id(patch: Mapping[str, object]) -> ElementId:
        """Return the patch's ``id`` or raise ``MalformedPatchError`` on absence."""
        raw = patch.get("id")
        if raw is None:
            raise MalformedPatchError(None, "patch is missing a required 'id'")
        return ElementId(str(raw))

    @staticmethod
    def _is_removal(patch: Mapping[str, object], element_id: ElementId) -> bool:
        """Return True if ``patch`` is a well-formed removal, False if a field set.

        A falsy or absent ``remove`` is a field set. A truthy ``remove`` must be
        exactly the boolean ``True`` and must not also carry a ``set`` — the two
        shapes are mutually exclusive. Any other combination raises.
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
