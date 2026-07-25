"""Scene-replacement messages — full-scene replace and clear."""

from __future__ import annotations

import base64
import pickle
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, Self, cast

from punt_lux.protocol.elements import (
    Element,
    _element_to_dict,
    _strip_none,
    container_dispatch,
)

__all__ = [
    "ClearMessage",
    "SceneMessage",
    "register_codecs",
]


@dataclass(frozen=True, slots=True)
class SceneMessage:
    """Replace the entire display contents, framing the scene it carries."""

    id: str
    elements: list[Element]
    frame_id: str  # required — no scene crosses the wire unframed (Hub self-frames)
    type: Literal["scene"] = "scene"
    layout: Literal["single", "rows", "columns", "grid"] = "single"
    title: str | None = None
    frame_title: str | None = None
    frame_size: tuple[int, int] | None = None
    frame_flags: dict[str, bool] | None = None
    frame_layout: Literal["tab", "stack"] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize the scene and frame; ABC elements cross as base64 pickles."""
        from punt_lux.domain.element_abc import Element as AbcElement

        elements: list[dict[str, Any]] = [
            {"_pickled": base64.b64encode(pickle.dumps(e)).decode("ascii")}
            if isinstance(e, AbcElement)
            else _element_to_dict(e)
            for e in self.elements
        ]
        return _strip_none(
            {
                "type": self.type,
                "id": self.id,
                "layout": self.layout,
                "title": self.title,
                "elements": elements,
                "frame_id": self.frame_id,
                "frame_title": self.frame_title,
                "frame_size": list(self.frame_size) if self.frame_size else None,
                "frame_flags": self.frame_flags,
                "frame_layout": self.frame_layout,
            }
        )

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Self:
        """Rebuild a scene from its wire dict, decoding each element and frame field."""
        raw_layout = d.get("frame_layout")
        layout = d.get("layout", "single")
        if layout not in ("single", "rows", "columns", "grid"):
            raise ValueError(f"layout must be single/rows/columns/grid, got {layout!r}")
        return cls(
            id=d["id"],
            elements=cls._decode_elements(d.get("elements")),
            frame_id=d["frame_id"],
            layout=layout,
            title=d.get("title"),
            frame_title=d.get("frame_title"),
            frame_size=cls._parse_frame_size(s) if (s := d.get("frame_size")) else None,
            frame_flags=cast("dict[str, bool]", f)
            if isinstance(f := d.get("frame_flags"), dict)
            else None,
            frame_layout=cast("Literal['tab', 'stack']", raw_layout)  # pyright: ignore[reportUnnecessaryCast]
            if raw_layout in ("tab", "stack")
            else None,
        )

    @staticmethod
    def _decode_elements(raw: object) -> list[Element]:
        """Decode the wire elements — omission/non-list is malformed, not empty-push.

        Each element is a pickled ABC object (``_pickled``) or a recursed legacy dict.
        """
        if not isinstance(raw, list):
            raise ValueError(f"scene elements must be a present list, got {raw!r}")
        return [
            cast("Element", pickle.loads(base64.b64decode(cast("str", e["_pickled"]))))
            if "_pickled" in e
            else cast("Element", container_dispatch.dispatch.from_dict(e))
            for e in cast("list[dict[str, Any]]", raw)
        ]

    @staticmethod
    def _parse_frame_size(raw: object) -> tuple[int, int] | None:
        """Convert a frame_size to a 2-tuple, or None if it is not a 2-sequence."""
        try:
            a, b = cast("tuple[int, int]", raw)
            return (int(a), int(b))
        except (TypeError, ValueError):
            return None


@dataclass(frozen=True, slots=True)
class ClearMessage:
    """Remove all content from the display."""

    type: Literal["clear"] = "clear"

    def to_dict(self) -> dict[str, Any]:
        """Serialize the clear signal to its one-field wire dict."""
        return {"type": self.type}

    @classmethod
    def from_dict(cls, _d: dict[str, Any]) -> Self:
        """Rebuild the clear signal; it carries no wire state."""
        return cls()


_Register = Callable[
    [str, type, Callable[..., dict[str, Any]], Callable[[dict[str, Any]], Any]],
    None,
]


def register_codecs(register: _Register) -> None:
    """Register this module's message codecs into a MessageRegistry."""
    register("scene", SceneMessage, SceneMessage.to_dict, SceneMessage.from_dict)
    register("clear", ClearMessage, ClearMessage.to_dict, ClearMessage.from_dict)
