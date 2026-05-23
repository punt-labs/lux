"""ButtonElement — a clickable button; implements domain.Element Protocol."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, Self

from punt_lux.protocol.elements.element_wire import ElementWireContext

__all__ = ["ButtonElement"]


@dataclass(frozen=True, slots=True)
class ButtonElement:
    """A clickable button.

    Variants:
      - ``small=True``: compact button (ImGui SmallButton)
      - ``arrow``: directional arrow button ("left"/"right"/"up"/"down")
    """

    id: str
    label: str
    kind: Literal["button"] = "button"
    # PY-TS-14: None = action defaults to element id (renderer-resolved).
    action: str | None = None
    disabled: bool = False
    small: bool = False
    # PY-TS-14: None = not an arrow button; otherwise left|right|up|down.
    arrow: str | None = None
    tooltip: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "kind": self.kind,
            "id": self.id,
            "label": self.label,
            "action": self.action,
        }
        if self.disabled:
            d["disabled"] = True
        if self.small:
            d["small"] = True
        if self.arrow is not None:
            d["arrow"] = self.arrow
        return {k: v for k, v in d.items() if v is not None}

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Self:
        # PY-TS-14 OK: action/arrow None = "use renderer default"; PY-EH-1.
        ctx = ElementWireContext.for_kind("button")
        return cls(
            id=ctx.require_str(d, "id"),
            label=ctx.optional_str(d, "label", default=""),
            action=ctx.optional_nullable_str(d, "action"),
            disabled=ctx.optional_bool(d, "disabled", default=False),
            small=ctx.optional_bool(d, "small", default=False),
            arrow=ctx.optional_nullable_str(d, "arrow"),
        )
