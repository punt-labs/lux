"""MarkdownElement — a block of rendered markdown text; implements domain.Element."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, Self

from punt_lux.protocol.elements.draw_wire import WireContext

__all__ = ["MarkdownElement"]


@dataclass(frozen=True, slots=True)
class MarkdownElement:
    """A block of rendered markdown text."""

    id: str
    content: str
    kind: Literal["markdown"] = "markdown"
    tooltip: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "id": self.id,
            "content": self.content,
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Self:
        ctx = WireContext.for_element("markdown")
        return cls(
            id=ctx.require_string(ctx.require_field(d, "id"), "id"),
            content=ctx.require_string(ctx.require_field(d, "content"), "content"),
        )
