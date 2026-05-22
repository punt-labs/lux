"""SeparatorElement — a visual divider; implements domain.Element."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, Self

__all__ = ["SeparatorElement"]


@dataclass(frozen=True, slots=True)
class SeparatorElement:
    """A visual divider.

    Anonymous separators (empty ``id``) are still supported on the wire —
    the codec omits the ``id`` key when it is the empty default — but the
    field type is now ``str`` to satisfy the Element Protocol's contract
    (PY-TS-14: empty-string = "anonymous", a value, not the absence of one).
    """

    kind: Literal["separator"] = "separator"
    id: str = ""
    tooltip: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"kind": self.kind}
        if self.id:
            d["id"] = self.id
        return d

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Self:
        return cls(id=d.get("id", ""))
