"""Bounded numeric value classes — ``Radius`` and ``Rounding``.

``Radius`` is strictly positive; ``Rounding`` is non-negative.  Both are
single-field frozen value classes with construction-time validation and a
``from_wire`` boundary constructor used by the draw-command decoder.

They live in their own module so ``draw_values`` keeps the three classes
every command references (``Point2``, ``Color``, ``Thickness``).  Radius
and Rounding are referenced by ``CircleCmd`` and ``RectCmd`` respectively
and never by line/triangle/text commands.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from punt_lux.protocol.elements.draw_wire import WireContext, coerce_number

__all__ = [
    "NO_ROUNDING",
    "Radius",
    "Rounding",
]


@dataclass(frozen=True, slots=True)
class Radius:
    """Strictly-positive circle radius."""

    value: float

    def __post_init__(self) -> None:
        coerced = coerce_number(self.value)
        if coerced is None or coerced <= 0:
            msg = f"Radius must be a number > 0; got {self.value!r}"
            raise ValueError(msg)
        object.__setattr__(self, "value", coerced)

    @classmethod
    def from_wire(
        cls,
        raw: object,
        *,
        ctx: WireContext,
        field: str,
    ) -> Radius:
        """Build a ``Radius`` from a wire value."""
        coerced = coerce_number(raw)
        if coerced is None or coerced <= 0:
            raise ctx.field_error(field, "a number > 0", raw)
        return cls(coerced)

    def to_wire(self) -> float:
        """Return the float wire form."""
        return self.value


@dataclass(frozen=True, slots=True)
class Rounding:
    """Non-negative corner radius for rectangles."""

    value: float

    def __post_init__(self) -> None:
        coerced = coerce_number(self.value)
        if coerced is None or coerced < 0:
            msg = f"Rounding must be a number >= 0; got {self.value!r}"
            raise ValueError(msg)
        object.__setattr__(self, "value", coerced)

    @classmethod
    def from_wire(
        cls,
        raw: object,
        *,
        ctx: WireContext,
        field: str,
    ) -> Rounding:
        """Build a ``Rounding`` from a wire value."""
        coerced = coerce_number(raw)
        if coerced is None or coerced < 0:
            raise ctx.field_error(field, "a number >= 0", raw)
        return cls(coerced)

    def to_wire(self) -> float:
        """Return the float wire form."""
        return self.value


NO_ROUNDING: Final = Rounding(0.0)
