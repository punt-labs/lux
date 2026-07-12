"""InspectionView — a queryable view over one ``inspect_scene`` response.

The Display replica answers ``inspect_scene`` with an ``element_paths``
array — one record per element (recursed through containers) carrying
``id``, ``kind``, ``render_path``, and ``props``. Both the loop invariants
and the re-push effects read that array by element id; this value class
owns the lookup so neither reaches into the raw dict shape.
"""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING, Self, cast

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ["InspectionView"]


class InspectionView:
    """Read an ``inspect_scene`` response by element id.

    Wraps the enriched ``inspect_scene`` dict and exposes its
    ``element_paths`` records by id — ``record`` for a required element
    (raises on absence, PY-EH-8) and ``has`` for a presence check.
    ``root_ids`` and ``duplicate_ids`` expose the scene's *shape* so a
    re-push that hoists a child to a top-level sibling (and duplicates it)
    is caught structurally, not only through a mutated prop.
    """

    _records: tuple[Mapping[str, object], ...]
    _root_ids: tuple[str, ...]

    def __new__(cls, inspection: Mapping[str, object]) -> Self:
        self = super().__new__(cls)
        paths = cast("list[Mapping[str, object]]", inspection["element_paths"])
        self._records = tuple(paths)
        roots = cast("list[Mapping[str, object]]", inspection["elements"])
        self._root_ids = tuple(cast("str", root["id"]) for root in roots)
        return self

    def record(self, element_id: str) -> Mapping[str, object]:
        """Return the ``element_paths`` record for ``element_id`` or raise."""
        for record in self._records:
            if record["id"] == element_id:
                return record
        msg = f"element {element_id!r} absent from inspect_scene element_paths"
        raise AssertionError(msg)

    def props(self, element_id: str) -> Mapping[str, object]:
        """Return the resolved props for ``element_id`` or raise."""
        return cast("Mapping[str, object]", self.record(element_id)["props"])

    def has(self, element_id: str) -> bool:
        """Return whether ``element_id`` appears in the inspection."""
        return any(record["id"] == element_id for record in self._records)

    def ids(self) -> frozenset[str]:
        """Return every element id present in the inspection."""
        return frozenset(cast("str", record["id"]) for record in self._records)

    def root_ids(self) -> frozenset[str]:
        """Return the ids of the scene's top-level roots.

        These are the ``elements`` the Hub re-pushed as roots. A child that
        was hoisted to a top-level sibling by a flattening re-push shows up
        here; a correctly-nested child never does.
        """
        return frozenset(self._root_ids)

    def duplicate_ids(self) -> frozenset[str]:
        """Return named ids that appear more than once across ``element_paths``.

        ``element_paths`` recurses containers, so each *named* element appears
        once in a well-formed scene. A named id appearing twice means the same
        element is both nested in its container and hoisted to a top-level
        root — the signature of a re-push that flattened the tree.

        Anonymous elements (the empty-id sentinel — bare separators) are
        exempt: they carry no identity and may repeat freely, so a scene with
        several separators is well-formed even though their ids collide. Only
        truthy string ids are counted, so an empty or non-string id never
        registers a false duplicate.
        """
        counts = Counter(
            eid
            for record in self._records
            if isinstance(eid := record["id"], str) and eid
        )
        return frozenset(eid for eid, count in counts.items() if count > 1)
