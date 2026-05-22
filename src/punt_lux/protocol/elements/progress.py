"""ProgressElement — a progress bar; implements domain.Element."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, Self

__all__ = ["ProgressElement"]


@dataclass(frozen=True, slots=True)
class ProgressElement:
    """A progress bar."""

    id: str
    kind: Literal["progress"] = "progress"
    fraction: float = 0.0
    label: str = ""
    tooltip: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "kind": self.kind,
            "id": self.id,
            "fraction": self.fraction,
        }
        if self.label:
            d["label"] = self.label
        return d

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Self:
        return cls(id=d["id"], fraction=d["fraction"], label=d.get("label", ""))
