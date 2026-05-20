"""Scene-replacement messages — full-scene replace, incremental patch, clear."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, cast

from punt_lux.protocol.elements import (
    Element,
    Patch,
    _element_to_dict,
    _strip_none,
    element_from_dict,
)
from punt_lux.protocol.elements.patch import _patch_from_dict, _patch_to_dict

__all__ = [
    "ClearMessage",
    "SceneMessage",
    "UpdateMessage",
    "register_codecs",
]


@dataclass(frozen=True, slots=True)
class SceneMessage:
    """Replace the entire display contents."""

    id: str
    elements: list[Element]
    type: Literal["scene"] = "scene"
    layout: str = "single"  # "single", "rows", "columns", "grid"
    title: str | None = None
    frame_id: str | None = None
    frame_title: str | None = None
    frame_size: tuple[int, int] | None = None
    frame_flags: dict[str, bool] | None = None
    frame_layout: Literal["tab", "stack"] | None = None


@dataclass(frozen=True, slots=True)
class UpdateMessage:
    """Incrementally patch the current scene."""

    scene_id: str
    patches: list[Patch]
    type: Literal["update"] = "update"


@dataclass(frozen=True, slots=True)
class ClearMessage:
    """Remove all content from the display."""

    type: Literal["clear"] = "clear"


def _parse_frame_size(raw: object) -> tuple[int, int] | None:
    """Validate and convert a frame_size value to a 2-tuple or None."""
    if not isinstance(raw, (list, tuple)):
        return None
    seq = cast("list[int]", raw)
    if len(seq) != 2:
        return None
    try:
        return (int(seq[0]), int(seq[1]))
    except (TypeError, ValueError):
        return None


def _scene_to_dict(msg: SceneMessage) -> dict[str, Any]:
    d: dict[str, Any] = {
        "type": msg.type,
        "id": msg.id,
        "layout": msg.layout,
        "title": msg.title,
        "elements": [_element_to_dict(e) for e in msg.elements],
        "frame_id": msg.frame_id,
        "frame_title": msg.frame_title,
        "frame_size": list(msg.frame_size) if msg.frame_size else None,
        "frame_flags": msg.frame_flags,
        "frame_layout": msg.frame_layout,
    }
    return _strip_none(d)


def _update_to_dict(msg: UpdateMessage) -> dict[str, Any]:
    return {
        "type": msg.type,
        "scene_id": msg.scene_id,
        "patches": [_patch_to_dict(p) for p in msg.patches],
    }


def _clear_to_dict(m: ClearMessage) -> dict[str, Any]:
    return {"type": m.type}


def _scene_from_dict(d: dict[str, Any]) -> SceneMessage:
    elements = [element_from_dict(e) for e in d.get("elements", [])]
    raw_frame_size = d.get("frame_size")
    frame_size = _parse_frame_size(raw_frame_size) if raw_frame_size else None
    raw_flags = d.get("frame_flags")
    frame_flags: dict[str, bool] | None = (
        cast("dict[str, bool]", raw_flags) if isinstance(raw_flags, dict) else None
    )
    raw_layout = d.get("frame_layout")
    frame_layout: Literal["tab", "stack"] | None = None
    if isinstance(raw_layout, str) and raw_layout in ("tab", "stack"):
        frame_layout = cast("Literal['tab', 'stack']", raw_layout)  # pyright: ignore[reportUnnecessaryCast]
    return SceneMessage(
        id=d["id"],
        elements=elements,
        layout=d.get("layout", "single"),
        title=d.get("title"),
        frame_id=d.get("frame_id"),
        frame_title=d.get("frame_title"),
        frame_size=frame_size,
        frame_flags=frame_flags,
        frame_layout=frame_layout,
    )


def _update_from_dict(d: dict[str, Any]) -> UpdateMessage:
    patches = [_patch_from_dict(p) for p in d.get("patches", [])]
    return UpdateMessage(scene_id=d["scene_id"], patches=patches)


def _clear_from_dict(_d: dict[str, Any]) -> ClearMessage:
    return ClearMessage()


_Register = Callable[
    [str, type, Callable[..., dict[str, Any]], Callable[[dict[str, Any]], Any]],
    None,
]


def register_codecs(register: _Register) -> None:
    """Register this module's message codecs into a MessageRegistry."""
    register("scene", SceneMessage, _scene_to_dict, _scene_from_dict)
    register("update", UpdateMessage, _update_to_dict, _update_from_dict)
    register("clear", ClearMessage, _clear_to_dict, _clear_from_dict)
