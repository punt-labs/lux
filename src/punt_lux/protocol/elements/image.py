"""ImageElement — bitmap / vector image; implements domain.Element."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, Self

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
        return cls(
            id=d["id"],
            path=d.get("path"),
            data=d.get("data"),
            format=d.get("format"),
            alt=d.get("alt"),
            width=d.get("width"),
            height=d.get("height"),
        )
