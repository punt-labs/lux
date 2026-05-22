"""TextElement — a text block; implements the domain.Element Protocol."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, Self

from punt_lux.protocol.elements.draw_wire import WireContext

__all__ = ["TextElement"]


@dataclass(frozen=True, slots=True)
class TextElement:
    """A text block."""

    id: str
    content: str
    kind: Literal["text"] = "text"
    style: str | None = None  # body|heading|caption|code|success|error
    tooltip: str | None = None
    color: str | None = None  # PY-TS-14: None = renderer default

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "kind": self.kind,
            "id": self.id,
            "content": self.content,
        }
        if self.style is not None:
            d["style"] = self.style
        if self.color is not None:
            d["color"] = self.color
        return d

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Self:
        ctx = WireContext.for_element("text")
        return cls(
            id=ctx.require_string(ctx.require_field(d, "id"), "id"),
            content=ctx.require_string(ctx.require_field(d, "content"), "content"),
            # PY-TS-14 OK: style absent => renderer body-default; present-but-non-str
            # raises (PY-EH-1 wire-boundary check).
            style=ctx.optional_nullable_string(d, "style"),
            # PY-TS-14 OK: color absent => renderer default; present-but-non-str raises.
            color=ctx.optional_nullable_string(d, "color"),
        )
