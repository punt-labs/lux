"""CheckboxElement — a boolean checkbox; implements domain.Element Protocol."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, Self

from punt_lux.protocol.elements.element_wire import ElementWireContext

__all__ = ["CheckboxElement"]


@dataclass(frozen=True, slots=True)
class CheckboxElement:
    """A boolean checkbox."""

    id: str
    label: str
    kind: Literal["checkbox"] = "checkbox"
    value: bool = False
    tooltip: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "id": self.id,
            "label": self.label,
            "value": self.value,
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Self:
        ctx = ElementWireContext.for_kind("checkbox")
        return cls(
            id=ctx.require_str(d, "id"),
            label=ctx.optional_str(d, "label", default=""),
            value=ctx.optional_bool(d, "value", default=False),
        )
