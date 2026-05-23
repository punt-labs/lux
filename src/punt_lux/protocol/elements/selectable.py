"""SelectableElement — a toggleable list item; implements domain.Element Protocol."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, Self

from punt_lux.protocol.elements.element_wire import ElementWireContext

__all__ = ["SelectableElement"]


@dataclass(frozen=True, slots=True)
class SelectableElement:
    """A toggleable list item."""

    id: str
    label: str
    kind: Literal["selectable"] = "selectable"
    selected: bool = False
    tooltip: str | None = None

    def widget_value(self) -> Any:
        """Return the selected bool SceneManager mirrors into WidgetState."""
        return self.selected

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "kind": self.kind,
            "id": self.id,
            "label": self.label,
        }
        if self.selected:
            d["selected"] = True
        return d

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Self:
        ctx = ElementWireContext.for_kind("selectable")
        return cls(
            id=ctx.require_str(d, "id"),
            label=ctx.optional_str(d, "label", default=""),
            selected=ctx.optional_bool(d, "selected", default=False),
        )
