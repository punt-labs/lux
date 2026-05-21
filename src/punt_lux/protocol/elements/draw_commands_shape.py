"""Closed-shape draw commands — ``RectCmd``, ``CircleCmd``, ``TriangleCmd``.

All three describe filled-or-outlined closed shapes. They compose
``Point2``, ``Color``, and ``Thickness`` from ``draw_values`` and (for
``RectCmd``/``CircleCmd``) the bounded numeric value classes from
``draw_bounds``. Each is a frozen, slotted dataclass whose ``kind`` is
locked to a single ``Literal[DrawCommandKind.<KIND>]``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, Self

from punt_lux.protocol.elements.draw_bounds import (
    NO_ROUNDING,
    Radius,
    Rounding,
)
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
    "CircleCmd",
    "RectCmd",
    "TriangleCmd",
]


@dataclass(frozen=True, slots=True)
class RectCmd:
    """Axis-aligned rectangle from ``min`` (top-left) to ``max`` (bottom-right)."""

    min: Point2
    max: Point2
    color: Color = WHITE
    thickness: Thickness = DEFAULT_THICKNESS
    rounding: Rounding = NO_ROUNDING
    filled: bool = False
    kind: Literal[DrawCommandKind.RECT] = DrawCommandKind.RECT

    def to_dict(self) -> WireDict:
        """Serialize this command to its wire dict form."""
        return {
            "cmd": self.kind.value,
            "min": self.min.to_list(),
            "max": self.max.to_list(),
            "color": self.color.to_wire(),
            "thickness": self.thickness.to_wire(),
            "rounding": self.rounding.to_wire(),
            "filled": self.filled,
        }

    @classmethod
    def from_wire(cls, d: Mapping[str, object], *, ctx: WireContext) -> Self:
        """Build a ``RectCmd`` from a wire dict."""
        return cls(
            min=Point2.from_wire(ctx.require_field(d, "min"), ctx=ctx, field="min"),
            max=Point2.from_wire(ctx.require_field(d, "max"), ctx=ctx, field="max"),
            color=Color.from_wire_optional(d, ctx=ctx, field="color", default=WHITE),
            thickness=Thickness.from_wire_optional(
                d, ctx=ctx, field="thickness", default=DEFAULT_THICKNESS
            ),
            rounding=Rounding.from_wire_optional(
                d, ctx=ctx, field="rounding", default=NO_ROUNDING
            ),
            filled=ctx.optional_bool(d, "filled", default=False),
        )


@dataclass(frozen=True, slots=True)
class CircleCmd:
    """Circle with ``center`` and ``radius``."""

    center: Point2
    radius: Radius
    color: Color = WHITE
    thickness: Thickness = DEFAULT_THICKNESS
    filled: bool = False
    kind: Literal[DrawCommandKind.CIRCLE] = DrawCommandKind.CIRCLE

    def to_dict(self) -> WireDict:
        """Serialize this command to its wire dict form."""
        return {
            "cmd": self.kind.value,
            "center": self.center.to_list(),
            "radius": self.radius.to_wire(),
            "color": self.color.to_wire(),
            "thickness": self.thickness.to_wire(),
            "filled": self.filled,
        }

    @classmethod
    def from_wire(cls, d: Mapping[str, object], *, ctx: WireContext) -> Self:
        """Build a ``CircleCmd`` from a wire dict."""
        return cls(
            center=Point2.from_wire(
                ctx.require_field(d, "center"), ctx=ctx, field="center"
            ),
            radius=Radius.from_wire(
                ctx.require_field(d, "radius"), ctx=ctx, field="radius"
            ),
            color=Color.from_wire_optional(d, ctx=ctx, field="color", default=WHITE),
            thickness=Thickness.from_wire_optional(
                d, ctx=ctx, field="thickness", default=DEFAULT_THICKNESS
            ),
            filled=ctx.optional_bool(d, "filled", default=False),
        )


@dataclass(frozen=True, slots=True)
class TriangleCmd:
    """Triangle through three points ``p1``, ``p2``, ``p3``."""

    p1: Point2
    p2: Point2
    p3: Point2
    color: Color = WHITE
    thickness: Thickness = DEFAULT_THICKNESS
    filled: bool = False
    kind: Literal[DrawCommandKind.TRIANGLE] = DrawCommandKind.TRIANGLE

    def to_dict(self) -> WireDict:
        """Serialize this command to its wire dict form."""
        return {
            "cmd": self.kind.value,
            "p1": self.p1.to_list(),
            "p2": self.p2.to_list(),
            "p3": self.p3.to_list(),
            "color": self.color.to_wire(),
            "thickness": self.thickness.to_wire(),
            "filled": self.filled,
        }

    @classmethod
    def from_wire(cls, d: Mapping[str, object], *, ctx: WireContext) -> Self:
        """Build a ``TriangleCmd`` from a wire dict."""
        return cls(
            p1=Point2.from_wire(ctx.require_field(d, "p1"), ctx=ctx, field="p1"),
            p2=Point2.from_wire(ctx.require_field(d, "p2"), ctx=ctx, field="p2"),
            p3=Point2.from_wire(ctx.require_field(d, "p3"), ctx=ctx, field="p3"),
            color=Color.from_wire_optional(d, ctx=ctx, field="color", default=WHITE),
            thickness=Thickness.from_wire_optional(
                d, ctx=ctx, field="thickness", default=DEFAULT_THICKNESS
            ),
            filled=ctx.optional_bool(d, "filled", default=False),
        )
