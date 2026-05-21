"""Typed value primitives shared by every draw command.

``Point2`` carries the ``[x, y]`` coordinate pair every shape needs.
``Color`` validates the ``#RRGGBB`` / ``#RRGGBBAA`` hex strings the
renderer expects.  ``Thickness`` is the strictly-positive stroke width
that line, rect, circle, triangle, polyline, and bezier commands share.

Each is a frozen, slotted dataclass with a ``__post_init__`` that runs
the construction-time bound check and a ``from_wire`` boundary
constructor.  The boundary constructor consumes a ``WireContext`` from
``draw_wire`` and reports any malformed input in the project's standard
``draw command [i] (kind) field 'name' must be ...; got ...`` form.  The
wire path validates types via the context; the direct constructor
trusts its type annotation.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import ClassVar, Final

from punt_lux.protocol.elements.draw_wire import WireContext

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

    def __post_init__(self) -> None:
        # bool is a subclass of int → coerces silently. Reject so the field
        # actually means what its annotation says.
        if isinstance(self.x, bool) or isinstance(self.y, bool):
            msg = f"Point2 coordinates must be numbers; got ({self.x!r}, {self.y!r})"
            raise ValueError(msg)
        # Normalise int inputs to float so to_list() always yields floats —
        # the annotation says float and the wire form must too.
        object.__setattr__(self, "x", float(self.x))
        object.__setattr__(self, "y", float(self.y))

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
        """Build a ``Point2`` from a wire 2-element ``[x, y]`` sequence.

        Reports any malformed input as a ``[x, y] number pair`` error.
        Inner primitive errors from ``WireContext.require_sequence`` and
        ``require_number`` chain via ``__cause__`` for debugging.
        """
        try:
            seq = ctx.require_sequence(raw, field)
        except ValueError as exc:
            raise ctx.field_error(field, "[x, y] number pair", raw) from exc
        if len(seq) != 2:
            raise ctx.field_error(field, "[x, y] number pair", raw)
        try:
            x = ctx.require_number(seq[0], f"{field}[0]")
            y = ctx.require_number(seq[1], f"{field}[1]")
        except ValueError as exc:
            raise ctx.field_error(field, "[x, y] number pair", raw) from exc
        return cls(x=x, y=y)


@dataclass(frozen=True, slots=True)
class Color:
    """Hex-encoded RGB(A) color: ``#RRGGBB`` or ``#RRGGBBAA``."""

    # Valid hex-string lengths: 7 for #RRGGBB, 9 for #RRGGBBAA.
    _VALID_LENGTHS: ClassVar[frozenset[int]] = frozenset({7, 9})

    value: str

    def __post_init__(self) -> None:
        v = self.value
        if not v.startswith("#") or len(v) not in Color._VALID_LENGTHS:
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
        """Build a ``Color`` from a wire value (a hex string).

        Reports any malformed input (wrong type or invalid format) as a
        ``hex color`` error — that's the domain-level expectation, more
        informative for the user than the underlying "must be string".
        """
        if not isinstance(raw, str):
            raise ctx.field_error(field, "hex color '#RRGGBB' or '#RRGGBBAA'", raw)
        try:
            return cls(raw)
        except ValueError as exc:
            raise ctx.field_error(
                field, "hex color '#RRGGBB' or '#RRGGBBAA'", raw
            ) from exc

    @classmethod
    def from_wire_optional(
        cls,
        d: Mapping[str, object],
        *,
        ctx: WireContext,
        field: str,
        default: Color,
    ) -> Color:
        """Decode ``d[field]`` to a ``Color``, or return ``default`` if absent."""
        if field not in d:
            return default
        return cls.from_wire(d[field], ctx=ctx, field=field)

    def to_wire(self) -> str:
        """Return the canonical hex-string wire form."""
        return self.value


WHITE: Final = Color("#FFFFFF")


@dataclass(frozen=True, slots=True)
class Thickness:
    """Strictly-positive stroke width."""

    value: float

    def __post_init__(self) -> None:
        # bool is a subclass of int → coerces silently through the float
        # annotation. Reject explicitly.
        if isinstance(self.value, bool) or self.value <= 0:
            msg = f"Thickness must be a number > 0; got {self.value!r}"
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
    ) -> Thickness:
        """Build a ``Thickness`` from a wire value."""
        n = ctx.require_number(raw, field)
        if n <= 0:
            raise ctx.field_error(field, "a number > 0", raw)
        return cls(n)

    @classmethod
    def from_wire_optional(
        cls,
        d: Mapping[str, object],
        *,
        ctx: WireContext,
        field: str,
        default: Thickness,
    ) -> Thickness:
        """Decode ``d[field]`` to a ``Thickness``, or return ``default`` if absent."""
        if field not in d:
            return default
        return cls.from_wire(d[field], ctx=ctx, field=field)

    def to_wire(self) -> float:
        """Return the float wire form."""
        return self.value


DEFAULT_THICKNESS: Final = Thickness(1.0)
