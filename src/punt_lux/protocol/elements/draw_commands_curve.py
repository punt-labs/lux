"""Curve-family draw commands — ``BezierCubicCmd``.

A cubic Bezier travels from ``p1`` to ``p4`` with ``p2`` and ``p3`` as
control points. The class is a frozen, slotted dataclass composing four
``Point2`` values plus ``Color`` and ``Thickness``.
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

__all__ = ["BezierCubicCmd"]


@dataclass(frozen=True, slots=True)
class BezierCubicCmd:
    """Cubic Bezier through ``p1``, ``p2`` (control), ``p3`` (control), ``p4``."""

    p1: Point2
    p2: Point2
    p3: Point2
    p4: Point2
    color: Color = WHITE
    thickness: Thickness = DEFAULT_THICKNESS
    kind: Literal[DrawCommandKind.BEZIER_CUBIC] = DrawCommandKind.BEZIER_CUBIC

    def to_dict(self) -> dict[str, Any]:
        """Serialize this command to its wire dict form."""
        return {
            "cmd": self.kind.value,
            "p1": self.p1.to_list(),
            "p2": self.p2.to_list(),
            "p3": self.p3.to_list(),
            "p4": self.p4.to_list(),
            "color": self.color.to_wire(),
            "thickness": self.thickness.to_wire(),
        }
