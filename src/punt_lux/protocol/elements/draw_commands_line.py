"""Line-family draw commands — ``LineCmd`` and ``PolylineCmd``.

Both render as connected line segments. ``LineCmd`` is a single segment;
``PolylineCmd`` is a sequence of ≥ 2 points, optionally closed. Both are
frozen, slotted dataclasses; both compose ``Point2``, ``Color``, and
``Thickness`` from the value modules. ``PolylineCmd`` adds a
``__post_init__`` that enforces the ≥ 2 points invariant — the value
classes can't see that constraint because it spans fields.
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

    def to_dict(self) -> WireDict:
        """Serialize this command to its wire dict form."""
        return {
            "cmd": self.kind.value,
            "p1": self.p1.to_list(),
            "p2": self.p2.to_list(),
            "color": self.color.to_wire(),
            "thickness": self.thickness.to_wire(),
        }

    @classmethod
    def from_wire(cls, d: Mapping[str, object], *, ctx: WireContext) -> Self:
        """Build a ``LineCmd`` from a wire dict."""
        return cls(
            p1=Point2.from_wire(ctx.require_field(d, "p1"), ctx=ctx, field="p1"),
            p2=Point2.from_wire(ctx.require_field(d, "p2"), ctx=ctx, field="p2"),
            color=Color.from_wire_optional(d, ctx=ctx, field="color", default=WHITE),
            thickness=Thickness.from_wire_optional(
                d, ctx=ctx, field="thickness", default=DEFAULT_THICKNESS
            ),
        )


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

    def to_dict(self) -> WireDict:
        """Serialize this command to its wire dict form."""
        return {
            "cmd": self.kind.value,
            "points": [p.to_list() for p in self.points],
            "color": self.color.to_wire(),
            "thickness": self.thickness.to_wire(),
            "closed": self.closed,
        }

    @classmethod
    def from_wire(cls, d: Mapping[str, object], *, ctx: WireContext) -> Self:
        """Build a ``PolylineCmd`` from a wire dict."""
        raw_points = ctx.require_field(d, "points")
        # require_sequence raises with a clear "must be a list or tuple"
        # message — let it propagate. Wrapping it in a higher-level
        # field_error would discard that information.
        seq = ctx.require_sequence(raw_points, "points")
        points = tuple(
            Point2.from_wire(p, ctx=ctx, field=f"points[{i}]")
            for i, p in enumerate(seq)
        )
        return cls(
            points=points,
            color=Color.from_wire_optional(d, ctx=ctx, field="color", default=WHITE),
            thickness=Thickness.from_wire_optional(
                d, ctx=ctx, field="thickness", default=DEFAULT_THICKNESS
            ),
            closed=ctx.optional_bool(d, "closed", default=False),
        )
