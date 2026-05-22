"""SpinnerElement — an animated loading spinner; implements domain.Element."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, Self

from punt_lux.protocol.elements.draw_wire import WireContext

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
        ctx = WireContext.for_element("spinner")
        return cls(
            id=ctx.require_string(ctx.require_field(d, "id"), "id"),
            # PY-TS-14 OK: label is genuinely optional UI text; absence means
            # "no label". Present-but-non-str raises (PY-EH-1).
            label=ctx.optional_string(d, "label", default=""),
            # PY-TS-14 OK: 16.0 is the spinner's default visual size;
            # PY-EH-1: type-check the float at the wire boundary.
            radius=ctx.optional_number(d, "radius", default=16.0),
            # PY-TS-14 OK: "#3399FF" is the brand default; absence means
            # "use the Lux default colour". Present-but-non-str raises.
            color=ctx.optional_string(d, "color", default="#3399FF"),
        )
