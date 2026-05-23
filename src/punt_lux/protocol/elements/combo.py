"""ComboElement — a dropdown combo box; implements domain.Element Protocol."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, Self

from punt_lux.protocol.elements.element_wire import ElementWireContext

__all__ = ["ComboElement"]


@dataclass(frozen=True, slots=True)
class ComboElement:
    """A dropdown combo box."""

    id: str
    label: str
    kind: Literal["combo"] = "combo"
    items: list[str] = field(default_factory=lambda: list[str]())
    selected: int = 0
    tooltip: str | None = None

    def widget_value(self) -> Any:
        """Return the selected index SceneManager mirrors into WidgetState."""
        return self.selected

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "id": self.id,
            "label": self.label,
            "items": self.items,
            "selected": self.selected,
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Self:
        ctx = ElementWireContext.for_kind("combo")
        return cls(
            id=ctx.require_str(d, "id"),
            label=ctx.optional_str(d, "label", default=""),
            items=ctx.optional_string_list(d, "items"),
            selected=ctx.optional_int_with_default(d, "selected", default=0),
        )
