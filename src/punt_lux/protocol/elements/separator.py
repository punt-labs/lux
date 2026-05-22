"""SeparatorElement — a visual divider; implements domain.Element."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, Self

from punt_lux.protocol.elements.draw_wire import WireContext

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
        ctx = WireContext.for_element("separator")
        # PY-TS-14 OK: "" is the documented "anonymous separator" value
        # (see class docstring). Present-but-non-str raises (PY-EH-1).
        return cls(id=ctx.optional_string(d, "id", default=""))
