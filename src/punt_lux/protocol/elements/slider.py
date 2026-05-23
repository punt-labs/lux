"""SliderElement — a numeric slider; implements domain.Element Protocol."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, Self

from punt_lux.protocol.elements.element_wire import ElementWireContext

__all__ = ["SliderElement"]


@dataclass(frozen=True, slots=True)
class SliderElement:
    """A numeric slider."""

    id: str
    label: str
    kind: Literal["slider"] = "slider"
    value: float = 0.0
    min: float = 0.0
    max: float = 100.0
    format: str = "%.1f"
    integer: bool = False
    tooltip: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "kind": self.kind,
            "id": self.id,
            "label": self.label,
            "value": self.value,
            "min": self.min,
            "max": self.max,
            "format": self.format,
        }
        if self.integer:
            d["integer"] = True
        return d

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Self:
        ctx = ElementWireContext.for_kind("slider")
        return cls(
            id=ctx.require_str(d, "id"),
            label=ctx.optional_str(d, "label", default=""),
            value=ctx.optional_number(d, "value", default=0.0),
            min=ctx.optional_number(d, "min", default=0.0),
            max=ctx.optional_number(d, "max", default=100.0),
            format=ctx.optional_str(d, "format", default="%.1f"),
            integer=ctx.optional_bool(d, "integer", default=False),
        )
