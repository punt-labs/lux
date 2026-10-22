"""Wire codec for the scene-replacement message — the sibling of ``scene.py``."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Literal, cast

from punt_lux.protocol.elements import _strip_none
from punt_lux.protocol.messages.pickled_element_codec import PickledElementCodec

if TYPE_CHECKING:
    from punt_lux.protocol.messages.scene import SceneMessage

__all__ = ["SceneCodec"]

logger = logging.getLogger(__name__)

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
                "frame_owner_facts": (
                    [[label, value] for label, value in msg.frame_owner_facts]
                    if msg.frame_owner_facts is not None
                    else None
                ),
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
            frame_size=cls._parse_frame_size(d.get("frame_size")),
            frame_flags=cls._parse_frame_flags(d.get("frame_flags")),
            frame_layout=cls._parse_frame_layout(d.get("frame_layout")),
            frame_owner_facts=cls._parse_owner_facts(d.get("frame_owner_facts")),
        )

    @staticmethod
    def _require_str(d: dict[str, Any], field: str) -> str:
        if not isinstance(value := d.get(field), str):
            raise ValueError(f"scene field {field!r} must be a str, got {value!r}")
        return value

    @staticmethod
    def _parse_frame_size(raw: object) -> tuple[int, int] | None:
        if not raw:
            return None
        try:
            a, b = cast("tuple[int, int]", raw)
            return (int(a), int(b))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _parse_frame_flags(raw: object) -> dict[str, bool] | None:
        return cast("dict[str, bool]", raw) if isinstance(raw, dict) else None

    @staticmethod
    def _parse_frame_layout(raw: object) -> Literal["tab", "stack"] | None:
        return raw if raw in ("tab", "stack") else None

    @staticmethod
    def _parse_owner_facts(raw: object) -> tuple[tuple[str, str], ...] | None:
        """Return the owning connection's rows, or ``None`` on absence/malformed.

        Absent and malformed both decode to ``None``. A non-None list the Hub
        serialized whose entries are not two-string rows signals protocol skew:
        the whole field degrades to ``None`` and is logged, never partly kept.
        """
        if not isinstance(raw, list):
            return None
        rows: list[tuple[str, str]] = []
        for entry in cast("list[object]", raw):
            match entry:
                case [str(first), str(second)]:
                    rows.append((first, second))
                case _:
                    logger.warning(
                        "frame_owner_facts contained a malformed entry: %r", entry
                    )
                    return None
        return tuple(rows)
