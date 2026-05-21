"""Typed value primitives shared by every draw command.

``Point2`` carries the ``[x, y]`` coordinate pair every shape needs.
``Color`` validates the ``#RRGGBB`` / ``#RRGGBBAA`` hex strings the
renderer expects.  ``Thickness`` is the strictly-positive stroke width
that line, rect, circle, triangle, polyline, and bezier commands share.

Each is a frozen, slotted dataclass with a ``__post_init__`` that runs
the construction-time invariant and a ``from_wire`` boundary
constructor.  The boundary constructor consumes a ``WireContext`` from
``draw_wire`` and reports any malformed input in the project's standard
``draw command [i] (kind) field 'name' must be ...; got ...`` form.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from punt_lux.protocol.elements.draw_wire import (
    WireContext,
    coerce_number,
    object_sequence,
)

__all__ = [
    "DEFAULT_THICKNESS",
    "WHITE",
    "Color",
    "Point2",
    "Thickness",
]


@dataclass(frozen=True, slots=True)
class Point2:
    """2D point with float coordinates; serializes as a ``[x, y]`` JSON array."""

    x: float
    y: float

    def to_list(self) -> list[float]:
        """Serialize to the wire-form ``[x, y]`` list."""
        return [self.x, self.y]

    @classmethod
    def from_wire(
        cls,
        raw: object,
        *,
        ctx: WireContext,
        field: str,
    ) -> Point2:
        """Build a ``Point2`` from a wire 2-element ``[x, y]`` sequence."""
        seq = object_sequence(raw)
        if seq is None or len(seq) != 2:
            raise ctx.field_error(field, "[x, y] number pair", raw)
        x = coerce_number(seq[0])
        y = coerce_number(seq[1])
        if x is None or y is None:
            raise ctx.field_error(field, "[x, y] number pair", raw)
        return cls(x=x, y=y)


_HEX_LENGTHS: Final = frozenset({7, 9})  # '#RRGGBB' or '#RRGGBBAA'


@dataclass(frozen=True, slots=True)
class Color:
    """Hex-encoded RGB(A) color: ``#RRGGBB`` or ``#RRGGBBAA``."""

    value: str

    def __post_init__(self) -> None:
        v = self.value
        if not v.startswith("#") or len(v) not in _HEX_LENGTHS:
            msg = f"Color must be hex string '#RRGGBB' or '#RRGGBBAA'; got {v!r}"
            raise ValueError(msg)
        try:
            int(v[1:], 16)
        except ValueError as exc:
            msg = f"Color must be hex string '#RRGGBB' or '#RRGGBBAA'; got {v!r}"
            raise ValueError(msg) from exc

    @classmethod
    def from_wire(
        cls,
        raw: object,
        *,
        ctx: WireContext,
        field: str,
    ) -> Color:
        """Build a ``Color`` from a wire value (a hex string)."""
        if not isinstance(raw, str):
            raise ctx.field_error(field, "hex color '#RRGGBB' or '#RRGGBBAA'", raw)
        try:
            return cls(raw)
        except ValueError as exc:
            raise ctx.field_error(
                field, "hex color '#RRGGBB' or '#RRGGBBAA'", raw
            ) from exc

    def to_wire(self) -> str:
        """Return the canonical hex-string wire form."""
        return self.value


WHITE: Final = Color("#FFFFFF")


@dataclass(frozen=True, slots=True)
class Thickness:
    """Strictly-positive stroke width."""

    value: float

    def __post_init__(self) -> None:
        coerced = coerce_number(self.value)
        if coerced is None or coerced <= 0:
            msg = f"Thickness must be a number > 0; got {self.value!r}"
            raise ValueError(msg)
        object.__setattr__(self, "value", coerced)

    @classmethod
    def from_wire(
        cls,
        raw: object,
        *,
        ctx: WireContext,
        field: str,
    ) -> Thickness:
        """Build a ``Thickness`` from a wire value."""
        coerced = coerce_number(raw)
        if coerced is None or coerced <= 0:
            raise ctx.field_error(field, "a number > 0", raw)
        return cls(coerced)

    def to_wire(self) -> float:
        """Return the float wire form."""
        return self.value


DEFAULT_THICKNESS: Final = Thickness(1.0)
