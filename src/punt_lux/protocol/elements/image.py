"""ImageElement — bitmap / vector image; implements domain.Element."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, Self

from punt_lux.protocol.elements.draw_wire import WireContext

__all__ = ["ImageElement"]


@dataclass(frozen=True, slots=True)
class ImageElement:
    """An image to display."""

    id: str
    kind: Literal["image"] = "image"
    # PY-TS-14 (path / data): exactly one is supplied; __post_init__ enforces.
    path: str | None = None
    data: str | None = None  # base64-encoded
    # PY-TS-14: None = "renderer infers from path / data".
    format: str | None = None  # png | jpeg | svg
    alt: str | None = None
    # PY-TS-14: None = "use natural pixel size".
    width: int | None = None
    height: int | None = None
    tooltip: str | None = None

    def __post_init__(self) -> None:
        if self.path is None and self.data is None:
            msg = "ImageElement requires either 'path' or 'data'"
            raise ValueError(msg)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"kind": self.kind, "id": self.id}
        for key in ("path", "data", "format", "alt", "width", "height"):
            value = getattr(self, key)
            if value is not None:
                d[key] = value
        return d

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Self:
        ctx = WireContext.for_element("image")
        # PY-TS-14 OK: each str field below is documented absent => None
        # (the renderer infers); present-but-non-str raises (PY-EH-1).
        # The path/data invariant is enforced by __post_init__.
        return cls(
            id=ctx.require_string(ctx.require_field(d, "id"), "id"),
            path=ctx.optional_nullable_string(d, "path"),
            data=ctx.optional_nullable_string(d, "data"),
            format=ctx.optional_nullable_string(d, "format"),
            alt=ctx.optional_nullable_string(d, "alt"),
            # PY-TS-14 OK: None => "use natural pixel size";
            # PY-EH-1: type-check the int at the wire boundary.
            width=ctx.optional_int(d, "width"),
            height=ctx.optional_int(d, "height"),
        )
