"""InputNumberElement — a numeric input with optional step + clamping bounds."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, Self

from punt_lux.protocol.elements.element_wire import ElementWireContext

__all__ = ["InputNumberElement"]


@dataclass(frozen=True, slots=True)
class InputNumberElement:
    """A numeric input field with optional step buttons and clamping."""

    id: str
    label: str
    kind: Literal["input_number"] = "input_number"
    value: float = 0.0
    # PY-TS-14: None = no lower bound; the renderer leaves the value unclamped.
    min: float | None = None
    # PY-TS-14: None = no upper bound; the renderer leaves the value unclamped.
    max: float | None = None
    # PY-TS-14: None = ImGui chooses a default step (0 — no step buttons).
    step: float | None = None
    format: str = "%.3f"
    integer: bool = False
    tooltip: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "kind": self.kind,
            "id": self.id,
            "label": self.label,
            "value": self.value,
            "format": self.format,
        }
        if self.min is not None:
            d["min"] = self.min
        if self.max is not None:
            d["max"] = self.max
        if self.step is not None:
            d["step"] = self.step
        if self.integer:
            d["integer"] = True
        return d

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Self:
        ctx = ElementWireContext.for_kind("input_number")
        return cls(
            id=ctx.require_str(d, "id"),
            label=ctx.optional_str(d, "label", default=""),
            value=ctx.optional_number(d, "value", default=0.0),
            min=ctx.optional_nullable_number(d, "min"),
            max=ctx.optional_nullable_number(d, "max"),
            step=ctx.optional_nullable_number(d, "step"),
            format=ctx.optional_str(d, "format", default="%.3f"),
            integer=ctx.optional_bool(d, "integer", default=False),
        )
