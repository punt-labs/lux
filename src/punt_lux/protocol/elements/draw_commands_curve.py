"""Curve-family draw commands — ``BezierCubicCmd``.

A cubic Bezier travels from ``p1`` to ``p4`` with ``p2`` and ``p3`` as
control points. The class is a frozen, slotted dataclass composing four
``Point2`` values plus ``Color`` and ``Thickness``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, Self

from punt_lux.protocol.elements.draw_command_kind import DrawCommandKind, WireDict
from punt_lux.protocol.elements.draw_values import (
    DEFAULT_THICKNESS,
    WHITE,
    Color,
    Point2,
    Thickness,
)
from punt_lux.protocol.elements.draw_wire import WireContext

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

    def to_dict(self) -> WireDict:
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

    @classmethod
    def from_wire(cls, d: Mapping[str, object], *, ctx: WireContext) -> Self:
        """Build a ``BezierCubicCmd`` from a wire dict."""
        pts = tuple(
            Point2.from_wire(ctx.require_field(d, name), ctx=ctx, field=name)
            for name in ("p1", "p2", "p3", "p4")
        )
        return cls(
            p1=pts[0],
            p2=pts[1],
            p3=pts[2],
            p4=pts[3],
            color=Color.from_wire_optional(d, ctx=ctx, field="color", default=WHITE),
            thickness=Thickness.from_wire_optional(
                d, ctx=ctx, field="thickness", default=DEFAULT_THICKNESS
            ),
        )
