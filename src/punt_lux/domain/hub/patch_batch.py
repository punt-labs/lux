"""Typed patch requests parsed from one agent ``update`` call.

The ``update`` tool submits a list of raw patch dicts — each an ``id`` plus a
``set`` mapping or a truthy ``remove``. :class:`PatchBatch.from_wire` is the
single place that wire shape becomes typed domain requests, so the tool layer
and the writer never hand-parse it. Each :class:`FieldPatch` owns the check and
commit of its own fields against an element (PY-OO-5), so the writer just
orchestrates ownership and re-push.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from typing import Self, cast

from punt_lux.domain.element_abc import Element as AbcElement
from punt_lux.domain.hub.patch_errors import MalformedPatchError
from punt_lux.domain.hub.write_result import WriteRejected
from punt_lux.domain.ids import ElementId
from punt_lux.domain.validation import ValidationReport

__all__ = ["FieldPatch", "PatchBatch"]


@dataclass(frozen=True, slots=True)
class FieldPatch:
    """The merged fields to write onto one element in an ``update`` batch."""

    element_id: ElementId
    # PY-TS-14: wire boundary — JSON object values arrive as ``object`` and are
    # coerced by each ``_set_<field>`` setter, so the value type stays open here.
    fields: Mapping[str, object]

    def rejection_against(self, element: AbcElement) -> WriteRejected | None:
        """Return why these fields may not be written to ``element``, or ``None``.

        Applies the fields to a throwaway copy so the live element is never
        touched by a rejected write. An unknown field is an agent error and
        reported cleanly; a setter that refuses a bad value (``TypeError`` /
        ``ValueError``) and a self-validation failure both surface here as the
        agent-facing reason. Any other exception is an internal bug in a setter
        and propagates rather than being laundered into a rejection.
        """
        for key in self.fields:
            if not callable(getattr(element, f"_set_{key}", None)):
                return WriteRejected(
                    f"cannot set unknown field {key!r} on element "
                    f"{str(self.element_id)!r}"
                )
        try:
            errors = deepcopy(element).apply_patch(self.fields).validate()
        except (ValueError, TypeError) as exc:
            return WriteRejected(str(exc))
        if errors:
            return WriteRejected(ValidationReport(errors).describe())
        return None

    def commit_to(self, element: AbcElement) -> None:
        """Write the fields onto the live ``element`` in place."""
        element.apply_patch(self.fields)


@dataclass(frozen=True, slots=True)
class PatchBatch:
    """One ``update`` call split into its field-set and removal requests."""

    field_patches: tuple[FieldPatch, ...]
    removals: tuple[ElementId, ...]

    @classmethod
    def from_wire(cls, patches: Sequence[Mapping[str, object]]) -> Self:
        """Build a batch from the ``update`` tool's raw patch dicts.

        Rejects a malformed patch loud (``MalformedPatchError``) rather than
        dropping it silently: every patch must carry an ``id`` and be either a
        truthy ``remove`` or a ``set`` mapping. Field patches on the same id are
        merged into one, so a duplicate id validates and commits as a single
        unit — two patches on one element can never leave a half-applied result
        behind.
        """
        merged: dict[ElementId, dict[str, object]] = {}
        order: list[ElementId] = []
        removals: list[ElementId] = []
        seen_removal: set[ElementId] = set()
        for patch in patches:
            element_id = cls._require_id(patch)
            if patch.get("remove", False):
                if element_id not in seen_removal:
                    seen_removal.add(element_id)
                    removals.append(element_id)
                continue
            fields = patch.get("set")
            if not isinstance(fields, Mapping):
                raise MalformedPatchError(
                    element_id,
                    "patch carries neither a truthy 'remove' nor a 'set' mapping",
                )
            if element_id not in merged:
                merged[element_id] = {}
                order.append(element_id)
            merged[element_id].update(cast("Mapping[str, object]", fields))
        field_patches = tuple(FieldPatch(eid, merged[eid]) for eid in order)
        return cls(field_patches, tuple(removals))

    @staticmethod
    def _require_id(patch: Mapping[str, object]) -> ElementId:
        """Return the patch's ``id`` or raise ``MalformedPatchError`` on absence."""
        raw = patch.get("id")
        if raw is None:
            raise MalformedPatchError(None, "patch is missing a required 'id'")
        return ElementId(str(raw))
