"""MarkdownElement — a block of rendered markdown text; implements domain.Element."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, Self

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
        return cls(id=d["id"], content=d["content"])
