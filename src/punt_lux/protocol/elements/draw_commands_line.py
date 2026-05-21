"""Line-family draw commands — ``LineCmd`` and ``PolylineCmd``.

Both render as connected line segments. ``LineCmd`` is a single segment;
``PolylineCmd`` is a sequence of ≥ 2 points, optionally closed. Both are
frozen, slotted dataclasses; both compose ``Point2``, ``Color``, and
``Thickness`` from the value modules. ``PolylineCmd`` adds a
``__post_init__`` that enforces the ≥ 2 points invariant — the value
classes can't see that constraint because it spans fields.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from punt_lux.protocol.elements.draw_command_kind import DrawCommandKind
from punt_lux.protocol.elements.draw_values import (
    DEFAULT_THICKNESS,
    WHITE,
    Color,
    Point2,
    Thickness,
)

__all__ = [
    "LineCmd",
    "PolylineCmd",
]


@dataclass(frozen=True, slots=True)
class LineCmd:
    """Straight line segment from ``p1`` to ``p2``."""

    p1: Point2
    p2: Point2
    color: Color = WHITE
    thickness: Thickness = DEFAULT_THICKNESS
    kind: Literal[DrawCommandKind.LINE] = DrawCommandKind.LINE

    def to_dict(self) -> dict[str, Any]:
        """Serialize this command to its wire dict form."""
        return {
            "cmd": self.kind.value,
            "p1": self.p1.to_list(),
            "p2": self.p2.to_list(),
            "color": self.color.to_wire(),
            "thickness": self.thickness.to_wire(),
        }


@dataclass(frozen=True, slots=True)
class PolylineCmd:
    """Connected line segments through ``points`` (≥ 2 points)."""

    points: tuple[Point2, ...]
    color: Color = WHITE
    thickness: Thickness = DEFAULT_THICKNESS
    closed: bool = False
    kind: Literal[DrawCommandKind.POLYLINE] = DrawCommandKind.POLYLINE

    def __post_init__(self) -> None:
        if len(self.points) < 2:
            msg = (
                "PolylineCmd field 'points' requires at least 2 points; "
                f"got {len(self.points)}"
            )
            raise ValueError(msg)

    def to_dict(self) -> dict[str, Any]:
        """Serialize this command to its wire dict form."""
        return {
            "cmd": self.kind.value,
            "points": [p.to_list() for p in self.points],
            "color": self.color.to_wire(),
            "thickness": self.thickness.to_wire(),
            "closed": self.closed,
        }
