"""Wire codec for the scene-replacement message — encode and decode over JSON.

Split out of ``scene.py`` so the ``SceneMessage`` dataclass stays a lean value
type: it keeps ``to_dict`` / ``from_dict`` as its public serialization surface and
delegates the work here. This is the same shape the element kinds use — a small
codec sibling that owns the wire mapping and its validation.
"""

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

_LAYOUTS = ("single", "rows", "columns", "grid")


class SceneCodec:
    """Encode a ``SceneMessage`` to its wire dict and decode one back, with validation.

    Every ``ValueError`` names the offending field and value so a malformed wire dict
    fails loud with the same shape at every boundary — a missing frame, a bad layout,
    an omitted or wrongly-typed element list, or a non-dict entry.
    """

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
    def decode(cls, message_cls: type[SceneMessage], d: dict[str, Any]) -> SceneMessage:
        """Rebuild a scene from its wire dict, validating every field."""
        layout = d.get("layout", "single")
        if layout not in _LAYOUTS:
            raise ValueError(f"layout must be single/rows/columns/grid, got {layout!r}")
        raw_layout = d.get("frame_layout")
        return message_cls(
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
        """Decode the wire elements — omission/non-list is malformed, not empty-push."""
        if not isinstance(raw, list):
            raise ValueError(f"scene elements must be a present list, got {raw!r}")
        return [SceneCodec._decode_entry(e) for e in cast("list[object]", raw)]

    @staticmethod
    def _decode_entry(e: object) -> Element:
        """Decode one entry: a dict (pickled ABC or legacy); else a named error."""
        if not isinstance(e, dict):
            raise ValueError(f"scene element must be a dict, got {e!r}")
        entry = cast("dict[str, Any]", e)
        pickled = entry.get("_pickled")
        if pickled is None:
            return cast("Element", container_dispatch.dispatch.from_dict(entry))
        if not isinstance(pickled, str):
            raise ValueError(f"scene element _pickled must be a str, got {pickled!r}")
        # Trusted, co-deployed Hub/Display IPC — the pickle producer is the Hub.
        return cast("Element", pickle.loads(base64.b64decode(pickled)))

    @staticmethod
    def _parse_frame_size(raw: object) -> tuple[int, int] | None:
        """Convert a frame_size to a 2-tuple, or None if it is not a 2-sequence."""
        try:
            a, b = cast("tuple[int, int]", raw)
            return (int(a), int(b))
        except (TypeError, ValueError):
            return None
