"""ProgressElement — a progress bar; implements domain.Element."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, Self

from punt_lux.protocol.elements.element_wire import ElementWireContext

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
        # PY-EH-1 + PY-TS-14 OK: fraction required; label="" => "no label".
        ctx = ElementWireContext.for_kind("progress")
        return cls(
            id=ctx.require_str(d, "id"),
            fraction=ctx.require_number(d, "fraction"),
            label=ctx.optional_str(d, "label", default=""),
        )
