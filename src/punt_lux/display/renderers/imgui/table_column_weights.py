"""Content-proportioned column stretch weights — pure, testable.

A grid with uniform stretch weights makes narrow columns (an id, a status) as
wide as long ones (a title), so the user resizes by hand. This derives a stretch
weight per column from the widest cell text in it (header included), clamped so
one very long value cannot starve the others and an empty column still gets a
usable share. The scan is bounded to a row sample so column setup stays cheap at
grid scale — it does not reintroduce the per-frame O(rows) cost the list clipper
removed from painting.
"""

from __future__ import annotations

from typing import Self, final

__all__ = ["ColumnWeights"]

_MIN_WEIGHT = 4.0  # a short column still gets a usable share
_MAX_WEIGHT = 40.0  # cap so one long cell cannot starve the rest
_SAMPLE_ROWS = 200  # bound the scan; representative without an O(rows) sweep


@final
class ColumnWeights:
    """Derive per-column stretch weights from cell content."""

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    def for_content(
        self,
        columns: tuple[str, ...],
        rows: tuple[tuple[object, ...], ...],
    ) -> tuple[float, ...]:
        """Return one clamped stretch weight per column, widest-text proportioned.

        The weight is the longest rendered text in the column — its header and up
        to ``_SAMPLE_ROWS`` cells — clamped to ``[_MIN_WEIGHT, _MAX_WEIGHT]``. A
        ragged row shorter than the column contributes nothing.
        """
        sample = rows[:_SAMPLE_ROWS]
        return tuple(
            self._clamp(self._widest(index, header, sample))
            for index, header in enumerate(columns)
        )

    @staticmethod
    def _widest(
        column: int, header: str, sample: tuple[tuple[object, ...], ...]
    ) -> int:
        """Return the longest rendered text length in ``column`` (header + sample)."""
        longest = len(header)
        for row in sample:
            if column < len(row):
                longest = max(longest, len(str(row[column])))
        return longest

    @staticmethod
    def _clamp(width: int) -> float:
        """Clamp a character width to the stretch-weight range."""
        return min(max(float(width), _MIN_WEIGHT), _MAX_WEIGHT)
