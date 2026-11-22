"""``Rect`` — a painted screen rectangle in the Display's coordinates.

The Display captures each painted element's screen rectangle at paint time and
answers a geometry query from it, so an agent can read back a rendered element's
actual size and position instead of asking a human to eyeball the window. A
``Rect`` is display-local truth: the Hub seeds an element's wire placement, but
the dragged position and ImGui's auto-sizing outcome live only on the Display
and cross back only as this read.

Coordinates are ImGui screen pixels — ``x``/``y`` is the top-left corner,
growing right and down from the viewport origin; ``width``/``height`` are the
painted extent.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Self

__all__ = ["Rect"]


@dataclass(frozen=True, slots=True)
class Rect:
    """A painted screen rectangle: top-left ``(x, y)`` plus ``width``/``height``."""

    x: float
    y: float
    width: float
    height: float

    def to_dict(self) -> dict[str, float]:
        """Serialize to the wire dict the geometry reply carries."""
        return {"x": self.x, "y": self.y, "width": self.width, "height": self.height}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Self:
        """Build a ``Rect`` from a wire dict.

        Every field must be present and numeric; a missing or non-numeric field
        raises ``ValueError`` here, so the geometry reply never yields a
        half-formed rect to a caller.
        """
        return cls(
            x=cls._require_number(d, "x"),
            y=cls._require_number(d, "y"),
            width=cls._require_number(d, "width"),
            height=cls._require_number(d, "height"),
        )

    @staticmethod
    def _require_number(d: dict[str, Any], field: str) -> float:
        """Return ``d[field]`` as a float or raise; ``bool`` is not a number."""
        raw = d.get(field)
        if isinstance(raw, bool) or not isinstance(raw, int | float):
            msg = f"Rect field {field!r} must be a number; got {raw!r}"
            raise ValueError(msg)
        return float(raw)
