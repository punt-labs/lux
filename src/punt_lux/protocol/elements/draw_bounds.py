"""Bounded numeric value classes — ``Radius`` and ``Rounding``.

``Radius`` is strictly positive; ``Rounding`` is non-negative.  Both are
single-field frozen value classes with a construction-time bound check
and a ``from_wire`` boundary constructor used by the draw-command
decoder.

They live in their own module so ``draw_values`` keeps the three classes
every command references (``Point2``, ``Color``, ``Thickness``).  Radius
and Rounding are referenced by ``CircleCmd`` and ``RectCmd`` respectively
and never by line/triangle/text commands.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from punt_lux.protocol.elements.draw_wire import WireContext

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
        # bool is a subclass of int → coerces silently. Reject explicitly.
        if isinstance(self.value, bool) or self.value <= 0:
            msg = f"Radius must be a number > 0; got {self.value!r}"
            raise ValueError(msg)
        # Normalise int inputs to float so to_wire() always yields a float.
        object.__setattr__(self, "value", float(self.value))

    @classmethod
    def from_wire(
        cls,
        raw: object,
        *,
        ctx: WireContext,
        field: str,
    ) -> Radius:
        """Build a ``Radius`` from a wire value."""
        n = ctx.require_number(raw, field)
        if n <= 0:
            raise ctx.field_error(field, "a number > 0", raw)
        return cls(n)

    def to_wire(self) -> float:
        """Return the float wire form."""
        return self.value


@dataclass(frozen=True, slots=True)
class Rounding:
    """Non-negative corner radius for rectangles."""

    value: float

    def __post_init__(self) -> None:
        # bool is a subclass of int → coerces silently. Reject explicitly.
        if isinstance(self.value, bool) or self.value < 0:
            msg = f"Rounding must be a number >= 0; got {self.value!r}"
            raise ValueError(msg)
        # Normalise int inputs to float so to_wire() always yields a float.
        object.__setattr__(self, "value", float(self.value))

    @classmethod
    def from_wire(
        cls,
        raw: object,
        *,
        ctx: WireContext,
        field: str,
    ) -> Rounding:
        """Build a ``Rounding`` from a wire value."""
        n = ctx.require_number(raw, field)
        if n < 0:
            raise ctx.field_error(field, "a number >= 0", raw)
        return cls(n)

    @classmethod
    def from_wire_optional(
        cls,
        d: Mapping[str, object],
        *,
        ctx: WireContext,
        field: str,
        default: Rounding,
    ) -> Rounding:
        """Decode ``d[field]`` to a ``Rounding``, or return ``default`` if absent."""
        if field not in d:
            return default
        return cls.from_wire(d[field], ctx=ctx, field=field)

    def to_wire(self) -> float:
        """Return the float wire form."""
        return self.value


NO_ROUNDING: Final = Rounding(0.0)
