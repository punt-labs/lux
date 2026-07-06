"""InspectionView — a queryable view over one ``inspect_scene`` response.

The Display replica answers ``inspect_scene`` with an ``element_paths``
array — one record per element (recursed through containers) carrying
``id``, ``kind``, ``render_path``, and ``props``. Both the loop invariants
and the re-push effects read that array by element id; this value class
owns the lookup so neither reaches into the raw dict shape.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, cast

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ["InspectionView"]


class InspectionView:
    """Read an ``inspect_scene`` response by element id.

    Wraps the enriched ``inspect_scene`` dict and exposes its
    ``element_paths`` records by id — ``record`` for a required element
    (raises on absence, PY-EH-8) and ``has`` for a presence check.
    """

    _records: tuple[Mapping[str, object], ...]

    def __new__(cls, inspection: Mapping[str, object]) -> Self:
        self = super().__new__(cls)
        paths = cast("list[Mapping[str, object]]", inspection["element_paths"])
        self._records = tuple(paths)
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
