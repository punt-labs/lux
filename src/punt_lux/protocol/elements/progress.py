"""ProgressElement — a progress bar; implements domain.Element."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, Self

from punt_lux.protocol.elements.draw_wire import WireContext

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
        ctx = WireContext.for_element("progress")
        return cls(
            id=ctx.require_string(ctx.require_field(d, "id"), "id"),
            # PY-EH-1: type-check the float at the wire boundary; raises on
            # missing key, str, bool, or None.
            fraction=ctx.require_number(ctx.require_field(d, "fraction"), "fraction"),
            # PY-TS-14 OK: label is genuinely optional UI text; absence means
            # "no label". Present-but-non-str raises (PY-EH-1).
            label=ctx.optional_string(d, "label", default=""),
        )
