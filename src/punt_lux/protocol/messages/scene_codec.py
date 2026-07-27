"""Wire codec for the scene-replacement message — the sibling of ``scene.py``."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal, cast

from punt_lux.protocol.elements import _strip_none
from punt_lux.protocol.messages.pickled_element_codec import PickledElementCodec

if TYPE_CHECKING:
    from punt_lux.protocol.messages.scene import SceneMessage

__all__ = ["SceneCodec"]

_ELEMENTS = PickledElementCodec()


class SceneCodec:
    """Encode/decode a ``SceneMessage`` to/from its wire dict, validating fields.

    Element transport is delegated to :class:`PickledElementCodec`; this codec
    owns only the scene/frame field mapping and its validation.
    """

    @staticmethod
    def encode(msg: SceneMessage) -> dict[str, Any]:
        """Serialize the scene and frame; every element crosses as a base64 pickle.

        Pickling preserves the Hub-side handlers the Display re-wraps for remote
        dispatch — every kind is an Element-ABC instance carrying them.
        """
        return _strip_none(
            {
                "type": msg.type,
                "id": msg.id,
                "layout": msg.layout,
                "title": msg.title,
                "elements": _ELEMENTS.encode_all(msg.elements),
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
            elements=_ELEMENTS.decode_all(d.get("elements")),
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
    def _parse_frame_size(raw: object) -> tuple[int, int] | None:
        try:
            a, b = cast("tuple[int, int]", raw)
            return (int(a), int(b))
        except (TypeError, ValueError):
            return None
