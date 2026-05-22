"""SpinnerElement — an animated loading spinner; implements domain.Element."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, Self

from punt_lux.protocol.elements.element_wire import ElementWireContext

__all__ = ["SpinnerElement"]


@dataclass(frozen=True, slots=True)
class SpinnerElement:
    """An animated loading spinner."""

    id: str
    kind: Literal["spinner"] = "spinner"
    label: str = ""
    radius: float = 16.0
    color: str = "#3399FF"
    tooltip: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "kind": self.kind,
            "id": self.id,
            "radius": self.radius,
            "color": self.color,
        }
        if self.label:
            d["label"] = self.label
        return d

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Self:
        # PY-TS-14 OK: label/radius/color have semantic defaults; PY-EH-1.
        ctx = ElementWireContext.for_kind("spinner")
        return cls(
            id=ctx.require_str(d, "id"),
            label=ctx.optional_str(d, "label", default=""),
            radius=ctx.optional_number(d, "radius", default=16.0),
            color=ctx.optional_str(d, "color", default="#3399FF"),
        )
