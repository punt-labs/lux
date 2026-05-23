"""ColorPickerElement — RGB(A) color picker; implements domain.Element."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, Self

from punt_lux.protocol.elements.element_wire import ElementWireContext

__all__ = ["ColorPickerElement"]


@dataclass(frozen=True, slots=True)
class ColorPickerElement:
    """A color picker with optional alpha channel and full picker mode.

    Modes:
      - default: inline ``ColorEdit3`` (RGB)
      - ``alpha=True``: ``ColorEdit4`` (RGBA), value uses ``#RRGGBBAA``
      - ``picker=True``: full ``ColorPicker3``/``ColorPicker4`` widget
    """

    id: str
    label: str
    kind: Literal["color_picker"] = "color_picker"
    value: str = "#FFFFFF"
    alpha: bool = False
    picker: bool = False
    tooltip: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "kind": self.kind,
            "id": self.id,
            "label": self.label,
            "value": self.value,
        }
        if self.alpha:
            d["alpha"] = True
        if self.picker:
            d["picker"] = True
        return d

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Self:
        ctx = ElementWireContext.for_kind("color_picker")
        return cls(
            id=ctx.require_str(d, "id"),
            label=ctx.optional_str(d, "label", default=""),
            value=ctx.optional_str(d, "value", default="#FFFFFF"),
            alpha=ctx.optional_bool(d, "alpha", default=False),
            picker=ctx.optional_bool(d, "picker", default=False),
        )
