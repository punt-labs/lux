"""SpinnerElement — an animated loading spinner; implements domain.Element."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, Self

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
        return cls(
            id=d["id"],
            label=d.get("label", ""),
            radius=d.get("radius", 16.0),
            color=d.get("color", "#3399FF"),
        )
