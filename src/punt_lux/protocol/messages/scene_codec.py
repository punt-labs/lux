"""Wire codec for the scene-replacement message — the sibling of ``scene.py``."""

from __future__ import annotations

import base64
import pickle
from typing import TYPE_CHECKING, Any, Literal, cast

from punt_lux.protocol.elements import (
    Element,
    _element_to_dict,
    _strip_none,
    container_dispatch,
)

if TYPE_CHECKING:
    from punt_lux.protocol.messages.scene import SceneMessage

__all__ = ["SceneCodec"]


class SceneCodec:
    """Encode/decode a ``SceneMessage`` to/from its wire dict, validating fields."""

    @staticmethod
    def encode(msg: SceneMessage) -> dict[str, Any]:
        """Serialize the scene and frame; ABC elements cross as base64 pickles."""
        from punt_lux.domain.element_abc import Element as AbcElement

        elements: list[dict[str, Any]] = [
            {"_pickled": base64.b64encode(pickle.dumps(e)).decode("ascii")}
            if isinstance(e, AbcElement)
            else _element_to_dict(e)
            for e in msg.elements
        ]
        return _strip_none(
            {
                "type": msg.type,
                "id": msg.id,
                "layout": msg.layout,
                "title": msg.title,
                "elements": elements,
                "frame_id": msg.frame_id,
                "frame_title": msg.frame_title,
                "frame_size": list(msg.frame_size) if msg.frame_size else None,
                "frame_flags": msg.frame_flags,
                "frame_layout": msg.frame_layout,
            }
        )

    @classmethod
    def decode(cls, d: dict[str, Any]) -> SceneMessage:
        """Rebuild a scene from its wire dict, validating every field."""
        from punt_lux.protocol.messages.scene import SceneMessage

        layout = d.get("layout", "single")
        if layout not in ("single", "rows", "columns", "grid"):
            raise ValueError(f"layout must be single/rows/columns/grid, got {layout!r}")
        return SceneMessage(
            id=cls._require_str(d, "id"),
            elements=cls._decode_elements(d.get("elements")),
            frame_id=cls._require_str(d, "frame_id"),
            layout=layout,
            title=d.get("title"),
            frame_title=d.get("frame_title"),
            frame_size=cls._parse_frame_size(s) if (s := d.get("frame_size")) else None,
            frame_flags=cast("dict[str, bool]", f)
            if isinstance(f := d.get("frame_flags"), dict)
            else None,
            frame_layout=cast("Literal['tab', 'stack']", rl)  # pyright: ignore[reportUnnecessaryCast]
            if (rl := d.get("frame_layout")) in ("tab", "stack")
            else None,
        )

    @staticmethod
    def _require_str(d: dict[str, Any], field: str) -> str:
        if not isinstance(value := d.get(field), str):
            raise ValueError(f"scene field {field!r} must be a str, got {value!r}")
        return value

    @staticmethod
    def _decode_elements(raw: object) -> list[Element]:
        """Decode the wire elements — omission/non-list is malformed, not empty-push."""
        if not isinstance(raw, list):
            raise ValueError(f"scene elements must be a present list, got {raw!r}")
        return [SceneCodec._decode_entry(e) for e in cast("list[object]", raw)]

    @staticmethod
    def _decode_entry(e: object) -> Element:
        if not isinstance(e, dict):
            raise ValueError(f"scene element must be a dict, got {e!r}")
        entry = cast("dict[str, Any]", e)
        pickled = entry.get("_pickled")
        if pickled is None:
            return cast("Element", container_dispatch.dispatch.from_dict(entry))
        return SceneCodec._unpickle(pickled)

    @staticmethod
    def _unpickle(pickled: object) -> Element:
        if not isinstance(pickled, str):
            raise ValueError(f"scene element _pickled must be a str, got {pickled!r}")
        try:
            return cast("Element", pickle.loads(base64.b64decode(pickled)))
        except (ValueError, EOFError, pickle.UnpicklingError) as exc:
            raise ValueError(f"scene element _pickled is not decodable: {exc}") from exc

    @staticmethod
    def _parse_frame_size(raw: object) -> tuple[int, int] | None:
        try:
            a, b = cast("tuple[int, int]", raw)
            return (int(a), int(b))
        except (TypeError, ValueError):
            return None
