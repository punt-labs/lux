"""InputTextElement — a single-line text input; implements domain.Element."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, Self

from punt_lux.protocol.elements.element_wire import ElementWireContext

__all__ = ["InputTextElement"]


@dataclass(frozen=True, slots=True)
class InputTextElement:
    """A single-line text input."""

    id: str
    label: str
    kind: Literal["input_text"] = "input_text"
    value: str = ""
    hint: str = ""
    tooltip: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "kind": self.kind,
            "id": self.id,
            "label": self.label,
            "value": self.value,
        }
        if self.hint:
            d["hint"] = self.hint
        return d

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Self:
        ctx = ElementWireContext.for_kind("input_text")
        return cls(
            id=ctx.require_str(d, "id"),
            label=ctx.optional_str(d, "label", default=""),
            value=ctx.optional_str(d, "value", default=""),
            hint=ctx.optional_str(d, "hint", default=""),
        )
