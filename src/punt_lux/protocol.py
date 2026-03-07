"""Lux display protocol v0.1 — message types, serialization, and framing.

Used by both client (MCP server / library) and display (ImGui renderer).

Wire format: 4-byte big-endian uint32 (payload length) + UTF-8 JSON payload.
Maximum message size: 16 MiB.
"""

from __future__ import annotations

import json
import socket
import struct
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal, cast

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PROTOCOL_VERSION = "0.1"
MAX_MESSAGE_SIZE = 16 * 1024 * 1024  # 16 MiB
HEADER_SIZE = 4
HEADER_FORMAT = "!I"  # big-endian uint32

# ---------------------------------------------------------------------------
# Element types (inside Scene messages)
# ---------------------------------------------------------------------------


@dataclass
class ImageElement:
    """An image to display."""

    id: str
    kind: Literal["image"] = "image"
    path: str | None = None
    data: str | None = None  # base64-encoded
    format: str | None = None  # "png", "jpeg", "svg"
    alt: str | None = None
    width: int | None = None
    height: int | None = None

    def __post_init__(self) -> None:
        if self.path is None and self.data is None:
            msg = "ImageElement requires either 'path' or 'data'"
            raise ValueError(msg)


@dataclass
class TextElement:
    """A text block."""

    id: str
    content: str
    kind: Literal["text"] = "text"
    style: str | None = None  # "body", "heading", "caption", "code"


@dataclass
class ButtonElement:
    """A clickable button."""

    id: str
    label: str
    kind: Literal["button"] = "button"
    action: str | None = None
    disabled: bool = False


@dataclass
class SeparatorElement:
    """A visual divider."""

    kind: Literal["separator"] = "separator"
    id: str | None = None


@dataclass
class SliderElement:
    """A numeric slider."""

    id: str
    label: str
    kind: Literal["slider"] = "slider"
    value: float = 0.0
    min: float = 0.0
    max: float = 100.0
    format: str = "%.1f"
    integer: bool = False


@dataclass
class CheckboxElement:
    """A boolean checkbox."""

    id: str
    label: str
    kind: Literal["checkbox"] = "checkbox"
    value: bool = False


@dataclass
class ComboElement:
    """A dropdown combo box."""

    id: str
    label: str
    kind: Literal["combo"] = "combo"
    items: list[str] = field(default_factory=lambda: list[str]())
    selected: int = 0


@dataclass
class InputTextElement:
    """A single-line text input."""

    id: str
    label: str
    kind: Literal["input_text"] = "input_text"
    value: str = ""
    hint: str = ""


@dataclass
class RadioElement:
    """A set of radio buttons."""

    id: str
    label: str
    kind: Literal["radio"] = "radio"
    items: list[str] = field(default_factory=lambda: list[str]())
    selected: int = 0


@dataclass
class ColorPickerElement:
    """An RGB color picker."""

    id: str
    label: str
    kind: Literal["color_picker"] = "color_picker"
    value: str = "#FFFFFF"


@dataclass
class DrawElement:
    """A 2D canvas with draw commands (line, rect, circle, etc.)."""

    id: str
    kind: Literal["draw"] = "draw"
    width: int = 400
    height: int = 300
    bg_color: str | None = None
    commands: list[dict[str, Any]] = field(
        default_factory=lambda: list[dict[str, Any]]()
    )


@dataclass
class GroupElement:
    """A layout container that arranges children in rows or columns."""

    id: str
    kind: Literal["group"] = "group"
    layout: str = "rows"  # "rows" | "columns"
    children: list[Any] = field(default_factory=lambda: list[Any]())


@dataclass
class TabBarElement:
    """A tabbed container. Each tab has a label and child elements."""

    id: str
    kind: Literal["tab_bar"] = "tab_bar"
    tabs: list[dict[str, Any]] = field(default_factory=lambda: list[dict[str, Any]]())


@dataclass
class CollapsingHeaderElement:
    """A collapsible section with a label and child elements."""

    id: str
    kind: Literal["collapsing_header"] = "collapsing_header"
    label: str = ""
    default_open: bool = False
    children: list[Any] = field(default_factory=lambda: list[Any]())


@dataclass
class WindowElement:
    """A movable, resizable sub-window inside the display."""

    id: str
    kind: Literal["window"] = "window"
    title: str = ""
    x: float = 50.0
    y: float = 50.0
    width: float = 300.0
    height: float = 200.0
    no_move: bool = False
    no_resize: bool = False
    no_collapse: bool = False
    no_title_bar: bool = False
    no_scrollbar: bool = False
    auto_resize: bool = False
    children: list[Any] = field(default_factory=lambda: list[Any]())


@dataclass
class SelectableElement:
    """A toggleable list item."""

    id: str
    label: str
    kind: Literal["selectable"] = "selectable"
    selected: bool = False


@dataclass
class TreeElement:
    """A collapsible tree with recursive nodes.

    Each node in ``nodes`` is a dict with ``"label"`` (str) and optional
    ``"children"`` (list of nodes).  Leaf nodes omit ``"children"`` or
    use an empty list.
    """

    id: str
    kind: Literal["tree"] = "tree"
    label: str = ""
    nodes: list[dict[str, Any]] = field(default_factory=lambda: list[dict[str, Any]]())


@dataclass
class TableElement:
    """A data table with columns and rows."""

    id: str
    kind: Literal["table"] = "table"
    columns: list[str] = field(default_factory=lambda: list[str]())
    rows: list[list[Any]] = field(default_factory=lambda: list[list[Any]]())
    flags: list[str] = field(default_factory=lambda: ["borders", "row_bg"])


Element = (
    ImageElement
    | TextElement
    | ButtonElement
    | SeparatorElement
    | SliderElement
    | CheckboxElement
    | ComboElement
    | InputTextElement
    | RadioElement
    | ColorPickerElement
    | DrawElement
    | GroupElement
    | TabBarElement
    | CollapsingHeaderElement
    | WindowElement
    | SelectableElement
    | TreeElement
    | TableElement
)

# ---------------------------------------------------------------------------
# Client -> Display messages
# ---------------------------------------------------------------------------


@dataclass
class Patch:
    """A single element patch within an UpdateMessage."""

    id: str
    set: dict[str, Any] | None = None
    remove: bool = False
    insert_after: dict[str, Any] | None = None


@dataclass
class SceneMessage:
    """Replace the entire display contents."""

    id: str
    elements: list[Element]
    type: Literal["scene"] = "scene"
    layout: str = "single"  # "single", "rows", "columns", "grid"
    title: str | None = None
    grid_columns: int | None = None


@dataclass
class UpdateMessage:
    """Incrementally patch the current scene."""

    scene_id: str
    patches: list[Patch]
    type: Literal["update"] = "update"


@dataclass
class ClearMessage:
    """Remove all content from the display."""

    type: Literal["clear"] = "clear"


@dataclass
class PingMessage:
    """Heartbeat / latency probe."""

    type: Literal["ping"] = "ping"
    ts: float | None = None


ClientMessage = SceneMessage | UpdateMessage | ClearMessage | PingMessage

# ---------------------------------------------------------------------------
# Display -> Client messages
# ---------------------------------------------------------------------------


@dataclass
class ReadyMessage:
    """Display is initialized and ready to render."""

    version: str = PROTOCOL_VERSION
    type: Literal["ready"] = "ready"
    capabilities: list[str] = field(default_factory=lambda: list[str]())


@dataclass
class AckMessage:
    """Acknowledges a scene or update."""

    scene_id: str
    type: Literal["ack"] = "ack"
    ts: float | None = None
    error: str | None = None


@dataclass
class InteractionMessage:
    """User interacted with an element."""

    element_id: str
    action: str
    type: Literal["interaction"] = "interaction"
    ts: float | None = None
    value: Any = None


@dataclass
class WindowMessage:
    """Window lifecycle event."""

    event: str  # "resized", "closed", "focused", "unfocused"
    type: Literal["window"] = "window"
    width: int | None = None
    height: int | None = None


@dataclass
class PongMessage:
    """Response to a ping."""

    type: Literal["pong"] = "pong"
    ts: float | None = None
    display_ts: float | None = None


DisplayMessage = (
    ReadyMessage | AckMessage | InteractionMessage | WindowMessage | PongMessage
)
Message = ClientMessage | DisplayMessage

# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def _strip_none(d: dict[str, Any]) -> dict[str, Any]:
    """Remove keys whose value is None."""
    return {k: v for k, v in d.items() if v is not None}


def _image_to_dict(elem: ImageElement) -> dict[str, Any]:
    return _strip_none(
        {
            "kind": elem.kind,
            "id": elem.id,
            "path": elem.path,
            "data": elem.data,
            "format": elem.format,
            "alt": elem.alt,
            "width": elem.width,
            "height": elem.height,
        }
    )


def _text_to_dict(elem: TextElement) -> dict[str, Any]:
    return _strip_none(
        {
            "kind": elem.kind,
            "id": elem.id,
            "content": elem.content,
            "style": elem.style,
        }
    )


def _button_to_dict(elem: ButtonElement) -> dict[str, Any]:
    d: dict[str, Any] = {
        "kind": elem.kind,
        "id": elem.id,
        "label": elem.label,
        "action": elem.action,
    }
    if elem.disabled:
        d["disabled"] = True
    return _strip_none(d)


def _separator_to_dict(elem: SeparatorElement) -> dict[str, Any]:
    d: dict[str, Any] = {"kind": elem.kind}
    if elem.id is not None:
        d["id"] = elem.id
    return d


def _slider_to_dict(elem: SliderElement) -> dict[str, Any]:
    d: dict[str, Any] = {
        "kind": elem.kind,
        "id": elem.id,
        "label": elem.label,
        "value": elem.value,
        "min": elem.min,
        "max": elem.max,
        "format": elem.format,
    }
    if elem.integer:
        d["integer"] = True
    return d


def _checkbox_to_dict(elem: CheckboxElement) -> dict[str, Any]:
    return {
        "kind": elem.kind,
        "id": elem.id,
        "label": elem.label,
        "value": elem.value,
    }


def _combo_to_dict(elem: ComboElement) -> dict[str, Any]:
    return {
        "kind": elem.kind,
        "id": elem.id,
        "label": elem.label,
        "items": elem.items,
        "selected": elem.selected,
    }


def _input_text_to_dict(elem: InputTextElement) -> dict[str, Any]:
    d: dict[str, Any] = {
        "kind": elem.kind,
        "id": elem.id,
        "label": elem.label,
        "value": elem.value,
    }
    if elem.hint:
        d["hint"] = elem.hint
    return d


def _radio_to_dict(elem: RadioElement) -> dict[str, Any]:
    return {
        "kind": elem.kind,
        "id": elem.id,
        "label": elem.label,
        "items": elem.items,
        "selected": elem.selected,
    }


def _color_picker_to_dict(elem: ColorPickerElement) -> dict[str, Any]:
    return {
        "kind": elem.kind,
        "id": elem.id,
        "label": elem.label,
        "value": elem.value,
    }


def _draw_to_dict(elem: DrawElement) -> dict[str, Any]:
    d: dict[str, Any] = {
        "kind": elem.kind,
        "id": elem.id,
        "width": elem.width,
        "height": elem.height,
        "commands": elem.commands,
    }
    if elem.bg_color is not None:
        d["bg_color"] = elem.bg_color
    return d


def _group_to_dict(elem: GroupElement) -> dict[str, Any]:
    return {
        "kind": elem.kind,
        "id": elem.id,
        "layout": elem.layout,
        "children": [_element_to_dict(c) for c in elem.children],
    }


def _tab_bar_to_dict(elem: TabBarElement) -> dict[str, Any]:
    return {
        "kind": elem.kind,
        "id": elem.id,
        "tabs": [
            {
                "label": t.get("label", "Tab"),
                "children": [_element_to_dict(c) for c in t.get("children", [])],
            }
            for t in elem.tabs
        ],
    }


def _collapsing_header_to_dict(elem: CollapsingHeaderElement) -> dict[str, Any]:
    d: dict[str, Any] = {
        "kind": elem.kind,
        "id": elem.id,
        "label": elem.label,
        "children": [_element_to_dict(c) for c in elem.children],
    }
    if elem.default_open:
        d["default_open"] = True
    return d


def _window_elem_to_dict(elem: WindowElement) -> dict[str, Any]:
    d: dict[str, Any] = {
        "kind": elem.kind,
        "id": elem.id,
        "title": elem.title,
        "x": elem.x,
        "y": elem.y,
        "width": elem.width,
        "height": elem.height,
        "children": [_element_to_dict(c) for c in elem.children],
    }
    if elem.no_move:
        d["no_move"] = True
    if elem.no_resize:
        d["no_resize"] = True
    if elem.no_collapse:
        d["no_collapse"] = True
    if elem.no_title_bar:
        d["no_title_bar"] = True
    if elem.no_scrollbar:
        d["no_scrollbar"] = True
    if elem.auto_resize:
        d["auto_resize"] = True
    return d


def _selectable_to_dict(elem: SelectableElement) -> dict[str, Any]:
    d: dict[str, Any] = {
        "kind": elem.kind,
        "id": elem.id,
        "label": elem.label,
    }
    if elem.selected:
        d["selected"] = True
    return d


def _tree_to_dict(elem: TreeElement) -> dict[str, Any]:
    return {
        "kind": elem.kind,
        "id": elem.id,
        "label": elem.label,
        "nodes": elem.nodes,
    }


def _table_to_dict(elem: TableElement) -> dict[str, Any]:
    return {
        "kind": elem.kind,
        "id": elem.id,
        "columns": elem.columns,
        "rows": elem.rows,
        "flags": elem.flags,
    }


_ELEMENT_SERIALIZERS: dict[type, Callable[..., dict[str, Any]]] = {
    ImageElement: _image_to_dict,
    TextElement: _text_to_dict,
    ButtonElement: _button_to_dict,
    SeparatorElement: _separator_to_dict,
    SliderElement: _slider_to_dict,
    CheckboxElement: _checkbox_to_dict,
    ComboElement: _combo_to_dict,
    InputTextElement: _input_text_to_dict,
    RadioElement: _radio_to_dict,
    ColorPickerElement: _color_picker_to_dict,
    DrawElement: _draw_to_dict,
    GroupElement: _group_to_dict,
    TabBarElement: _tab_bar_to_dict,
    CollapsingHeaderElement: _collapsing_header_to_dict,
    WindowElement: _window_elem_to_dict,
    SelectableElement: _selectable_to_dict,
    TreeElement: _tree_to_dict,
    TableElement: _table_to_dict,
}


def _element_to_dict(elem: Element) -> dict[str, Any]:
    """Serialize an Element dataclass to a JSON-compatible dict."""
    serializer = _ELEMENT_SERIALIZERS.get(type(elem))
    if serializer is not None:
        result: dict[str, Any] = serializer(elem)
        return result
    msg = f"Unknown element type: {type(elem)}"
    raise TypeError(msg)


def _image_from_dict(d: dict[str, Any]) -> ImageElement:
    return ImageElement(
        id=d["id"],
        path=d.get("path"),
        data=d.get("data"),
        format=d.get("format"),
        alt=d.get("alt"),
        width=d.get("width"),
        height=d.get("height"),
    )


def _text_from_dict(d: dict[str, Any]) -> TextElement:
    return TextElement(id=d["id"], content=d.get("content", ""), style=d.get("style"))


def _button_from_dict(d: dict[str, Any]) -> ButtonElement:
    return ButtonElement(
        id=d["id"],
        label=d.get("label", ""),
        action=d.get("action"),
        disabled=d.get("disabled", False),
    )


def _separator_from_dict(d: dict[str, Any]) -> SeparatorElement:
    return SeparatorElement(id=d.get("id"))


def _slider_from_dict(d: dict[str, Any]) -> SliderElement:
    return SliderElement(
        id=d["id"],
        label=d.get("label", ""),
        value=d.get("value", 0.0),
        min=d.get("min", 0.0),
        max=d.get("max", 100.0),
        format=d.get("format", "%.1f"),
        integer=d.get("integer", False),
    )


def _checkbox_from_dict(d: dict[str, Any]) -> CheckboxElement:
    return CheckboxElement(
        id=d["id"],
        label=d.get("label", ""),
        value=d.get("value", False),
    )


def _combo_from_dict(d: dict[str, Any]) -> ComboElement:
    return ComboElement(
        id=d["id"],
        label=d.get("label", ""),
        items=d.get("items", []),
        selected=d.get("selected", 0),
    )


def _input_text_from_dict(d: dict[str, Any]) -> InputTextElement:
    return InputTextElement(
        id=d["id"],
        label=d.get("label", ""),
        value=d.get("value", ""),
        hint=d.get("hint", ""),
    )


def _radio_from_dict(d: dict[str, Any]) -> RadioElement:
    return RadioElement(
        id=d["id"],
        label=d.get("label", ""),
        items=d.get("items", []),
        selected=d.get("selected", 0),
    )


def _color_picker_from_dict(d: dict[str, Any]) -> ColorPickerElement:
    return ColorPickerElement(
        id=d["id"],
        label=d.get("label", ""),
        value=d.get("value", "#FFFFFF"),
    )


def _draw_from_dict(d: dict[str, Any]) -> DrawElement:
    return DrawElement(
        id=d["id"],
        width=d.get("width", 400),
        height=d.get("height", 300),
        bg_color=d.get("bg_color"),
        commands=d.get("commands", []),
    )


def _group_from_dict(d: dict[str, Any]) -> GroupElement:
    return GroupElement(
        id=d["id"],
        layout=d.get("layout", "rows"),
        children=[element_from_dict(c) for c in d.get("children", [])],
    )


def _tab_bar_from_dict(d: dict[str, Any]) -> TabBarElement:
    tabs: list[dict[str, Any]] = [
        {
            "label": t.get("label", "Tab"),
            "children": [element_from_dict(c) for c in t.get("children", [])],
        }
        for t in d.get("tabs", [])
    ]
    return TabBarElement(id=d["id"], tabs=tabs)


def _collapsing_header_from_dict(d: dict[str, Any]) -> CollapsingHeaderElement:
    return CollapsingHeaderElement(
        id=d["id"],
        label=d.get("label", ""),
        default_open=d.get("default_open", False),
        children=[element_from_dict(c) for c in d.get("children", [])],
    )


def _window_from_dict(d: dict[str, Any]) -> WindowElement:
    return WindowElement(
        id=d["id"],
        title=d.get("title", ""),
        x=d.get("x", 50.0),
        y=d.get("y", 50.0),
        width=d.get("width", 300.0),
        height=d.get("height", 200.0),
        no_move=d.get("no_move", False),
        no_resize=d.get("no_resize", False),
        no_collapse=d.get("no_collapse", False),
        no_title_bar=d.get("no_title_bar", False),
        no_scrollbar=d.get("no_scrollbar", False),
        auto_resize=d.get("auto_resize", False),
        children=[element_from_dict(c) for c in d.get("children", [])],
    )


def _selectable_from_dict(d: dict[str, Any]) -> SelectableElement:
    return SelectableElement(
        id=d["id"],
        label=d.get("label", ""),
        selected=d.get("selected", False),
    )


def _normalize_tree_nodes(raw: Any) -> list[dict[str, Any]]:
    """Coerce tree nodes to a valid list of node dicts, non-mutating."""
    if not isinstance(raw, list):
        return []
    result: list[dict[str, Any]] = []
    for item in cast("list[Any]", raw):  # type: ignore[redundant-cast]
        if not isinstance(item, dict):
            continue
        src = cast("dict[str, Any]", item)
        node: dict[str, Any] = {k: v for k, v in src.items() if k != "children"}
        raw_children = src.get("children")
        if raw_children is not None:
            node["children"] = _normalize_tree_nodes(raw_children)
        result.append(node)
    return result


def _tree_from_dict(d: dict[str, Any]) -> TreeElement:
    return TreeElement(
        id=d["id"],
        label=d.get("label", ""),
        nodes=_normalize_tree_nodes(d.get("nodes", [])),
    )


def _table_from_dict(d: dict[str, Any]) -> TableElement:
    return TableElement(
        id=d["id"],
        columns=d.get("columns", []),
        rows=d.get("rows", []),
        flags=d.get("flags", ["borders", "row_bg"]),
    )


_ELEMENT_DESERIALIZERS: dict[str, Callable[[dict[str, Any]], Element]] = {
    "image": _image_from_dict,
    "text": _text_from_dict,
    "button": _button_from_dict,
    "separator": _separator_from_dict,
    "slider": _slider_from_dict,
    "checkbox": _checkbox_from_dict,
    "combo": _combo_from_dict,
    "input_text": _input_text_from_dict,
    "radio": _radio_from_dict,
    "color_picker": _color_picker_from_dict,
    "draw": _draw_from_dict,
    "group": _group_from_dict,
    "tab_bar": _tab_bar_from_dict,
    "collapsing_header": _collapsing_header_from_dict,
    "window": _window_from_dict,
    "selectable": _selectable_from_dict,
    "tree": _tree_from_dict,
    "table": _table_from_dict,
}


def element_from_dict(d: dict[str, Any]) -> Element:
    """Deserialize a dict to the appropriate Element dataclass.

    Accepts dicts matching this module's element schema or as supplied by
    MCP tool callers.  Missing ``content``/``label`` keys default to ``""``.
    """
    kind = d.get("kind", "text")
    deserializer = _ELEMENT_DESERIALIZERS.get(kind)
    if deserializer is not None:
        return deserializer(d)
    msg = f"Unknown element kind: {kind!r}"
    raise ValueError(msg)


def _patch_to_dict(p: Patch) -> dict[str, Any]:
    d: dict[str, Any] = {"id": p.id}
    if p.set is not None:
        d["set"] = p.set
    if p.remove:
        d["remove"] = True
    if p.insert_after is not None:
        d["insert_after"] = p.insert_after
    return d


def _patch_from_dict(d: dict[str, Any]) -> Patch:
    return Patch(
        id=d["id"],
        set=d.get("set"),
        remove=d.get("remove", False),
        insert_after=d.get("insert_after"),
    )


def _scene_to_dict(msg: SceneMessage) -> dict[str, Any]:
    d: dict[str, Any] = {
        "type": msg.type,
        "id": msg.id,
        "layout": msg.layout,
        "title": msg.title,
        "grid_columns": msg.grid_columns,
        "elements": [_element_to_dict(e) for e in msg.elements],
    }
    return _strip_none(d)


def _update_to_dict(msg: UpdateMessage) -> dict[str, Any]:
    return {
        "type": msg.type,
        "scene_id": msg.scene_id,
        "patches": [_patch_to_dict(p) for p in msg.patches],
    }


def _interaction_to_dict(msg: InteractionMessage) -> dict[str, Any]:
    d: dict[str, Any] = {
        "type": msg.type,
        "element_id": msg.element_id,
        "action": msg.action,
    }
    if msg.ts is not None:
        d["ts"] = msg.ts
    if msg.value is not None:
        d["value"] = msg.value
    return d


def _window_to_dict(msg: WindowMessage) -> dict[str, Any]:
    d: dict[str, Any] = {"type": msg.type, "event": msg.event}
    if msg.width is not None:
        d["width"] = msg.width
    if msg.height is not None:
        d["height"] = msg.height
    return d


def _ts_dict(msg_type: str, ts: float | None) -> dict[str, Any]:
    d: dict[str, Any] = {"type": msg_type}
    if ts is not None:
        d["ts"] = ts
    return d


_MessageSerializer = Callable[..., dict[str, Any]]
_MESSAGE_SERIALIZERS: dict[type, _MessageSerializer] = {}


def message_to_dict(msg: Message) -> dict[str, Any]:
    """Serialize a Message dataclass to a JSON-compatible dict."""
    serializer = _MESSAGE_SERIALIZERS.get(type(msg))
    if serializer is not None:
        result: dict[str, Any] = serializer(msg)
        return result
    msg_str = f"Unknown message type: {type(msg)}"
    raise TypeError(msg_str)


def _register_serializers() -> None:
    _MESSAGE_SERIALIZERS[SceneMessage] = _scene_to_dict
    _MESSAGE_SERIALIZERS[UpdateMessage] = _update_to_dict
    _MESSAGE_SERIALIZERS[InteractionMessage] = _interaction_to_dict
    _MESSAGE_SERIALIZERS[WindowMessage] = _window_to_dict

    def _clear(m: ClearMessage) -> dict[str, Any]:
        return {"type": m.type}

    def _ping(m: PingMessage) -> dict[str, Any]:
        return _ts_dict(m.type, m.ts)

    _MESSAGE_SERIALIZERS[ClearMessage] = _clear
    _MESSAGE_SERIALIZERS[PingMessage] = _ping

    def _ready(m: ReadyMessage) -> dict[str, Any]:
        d: dict[str, Any] = {"type": m.type, "version": m.version}
        if m.capabilities:
            d["capabilities"] = m.capabilities
        return d

    _MESSAGE_SERIALIZERS[ReadyMessage] = _ready

    def _ack(m: AckMessage) -> dict[str, Any]:
        d: dict[str, Any] = {"type": m.type, "scene_id": m.scene_id}
        if m.ts is not None:
            d["ts"] = m.ts
        if m.error is not None:
            d["error"] = m.error
        return d

    _MESSAGE_SERIALIZERS[AckMessage] = _ack

    def _pong(m: PongMessage) -> dict[str, Any]:
        d = _ts_dict(m.type, m.ts)
        if m.display_ts is not None:
            d["display_ts"] = m.display_ts
        return d

    _MESSAGE_SERIALIZERS[PongMessage] = _pong


_register_serializers()


def message_from_dict(d: dict[str, Any]) -> Message:
    """Deserialize a JSON dict to the appropriate Message dataclass."""
    msg_type = d.get("type", "")

    if msg_type == "scene":
        elements = [element_from_dict(e) for e in d.get("elements", [])]
        return SceneMessage(
            id=d["id"],
            elements=elements,
            layout=d.get("layout", "single"),
            title=d.get("title"),
            grid_columns=d.get("grid_columns"),
        )
    if msg_type == "update":
        patches = [_patch_from_dict(p) for p in d.get("patches", [])]
        return UpdateMessage(scene_id=d["scene_id"], patches=patches)
    if msg_type == "clear":
        return ClearMessage()
    if msg_type == "ping":
        return PingMessage(ts=d.get("ts"))
    if msg_type == "ready":
        return ReadyMessage(
            version=d.get("version", PROTOCOL_VERSION),
            capabilities=d.get("capabilities", []),
        )
    if msg_type == "ack":
        return AckMessage(scene_id=d["scene_id"], ts=d.get("ts"), error=d.get("error"))
    if msg_type == "interaction":
        return InteractionMessage(
            element_id=d["element_id"],
            action=d["action"],
            ts=d.get("ts"),
            value=d.get("value"),
        )
    if msg_type == "window":
        return WindowMessage(
            event=d["event"], width=d.get("width"), height=d.get("height")
        )
    if msg_type == "pong":
        return PongMessage(ts=d.get("ts"), display_ts=d.get("display_ts"))

    err = f"Unknown message type: {msg_type!r}"
    raise ValueError(err)


# ---------------------------------------------------------------------------
# Wire framing
# ---------------------------------------------------------------------------


def encode_frame(payload: dict[str, Any]) -> bytes:
    """Encode a JSON dict as a length-prefixed wire frame."""
    data = json.dumps(payload).encode("utf-8")
    if len(data) > MAX_MESSAGE_SIZE:
        msg = f"Message exceeds maximum size: {len(data)} > {MAX_MESSAGE_SIZE}"
        raise ValueError(msg)
    return struct.pack(HEADER_FORMAT, len(data)) + data


def encode_message(msg: Message) -> bytes:
    """Serialize a Message dataclass to a length-prefixed wire frame."""
    return encode_frame(message_to_dict(msg))


def decode_frame(data: bytes) -> tuple[dict[str, Any], bytes]:
    """Decode one length-prefixed frame from a byte buffer.

    Returns (decoded_message, remaining_bytes).
    """
    if len(data) < HEADER_SIZE:
        msg = "Incomplete frame header"
        raise ValueError(msg)
    (length,) = struct.unpack(HEADER_FORMAT, data[:HEADER_SIZE])
    if length > MAX_MESSAGE_SIZE:
        msg = f"Message exceeds maximum size: {length} > {MAX_MESSAGE_SIZE}"
        raise ValueError(msg)
    if len(data) < HEADER_SIZE + length:
        msg = "Incomplete frame payload"
        raise ValueError(msg)
    raw = json.loads(data[HEADER_SIZE : HEADER_SIZE + length])
    if not isinstance(raw, dict):
        msg = f"Expected JSON object, got {type(raw).__name__}"
        raise ValueError(msg)
    return cast("dict[str, Any]", raw), data[HEADER_SIZE + length :]


class FrameReader:
    """Accumulates bytes from a socket and yields complete messages.

    Call ``feed()`` with bytes from ``socket.recv()``, then iterate
    ``drain()`` for decoded messages. Handles partial reads gracefully.
    """

    def __init__(self) -> None:
        self._buf = bytearray()

    @property
    def buffer_size(self) -> int:
        """Current size of the internal read buffer in bytes."""
        return len(self._buf)

    def feed(self, data: bytes) -> None:
        """Append raw bytes received from the socket."""
        self._buf.extend(data)

    def drain(self) -> list[dict[str, Any]]:
        """Extract all complete messages from the buffer as raw dicts."""
        messages: list[dict[str, Any]] = []
        while len(self._buf) >= HEADER_SIZE:
            (payload_len,) = struct.unpack_from(HEADER_FORMAT, self._buf, 0)
            if payload_len > MAX_MESSAGE_SIZE:
                err = (
                    f"Message exceeds maximum size: {payload_len} > {MAX_MESSAGE_SIZE}"
                )
                raise ValueError(err)
            total = HEADER_SIZE + payload_len
            if len(self._buf) < total:
                break
            payload_bytes = bytes(self._buf[HEADER_SIZE:total])
            raw = json.loads(payload_bytes)
            if not isinstance(raw, dict):
                msg = f"Expected JSON object, got {type(raw).__name__}"
                raise ValueError(msg)
            del self._buf[:total]
            messages.append(cast("dict[str, Any]", raw))
        return messages

    def drain_typed(self) -> list[Message]:
        """Like drain(), but returns typed Message dataclasses."""
        return [message_from_dict(d) for d in self.drain()]


# ---------------------------------------------------------------------------
# Blocking socket helpers (for clients and tests)
# ---------------------------------------------------------------------------


def send_message(sock: socket.socket, msg: Message) -> None:
    """Send a framed message over a blocking socket."""
    sock.sendall(encode_message(msg))


def recv_message(sock: socket.socket, timeout: float = 5.0) -> Message | None:
    """Receive a single framed message. Returns None on timeout."""
    prev_timeout = sock.gettimeout()
    sock.settimeout(timeout)
    try:
        header = _recv_exact(sock, HEADER_SIZE)
        if header is None:
            return None
        (payload_len,) = struct.unpack(HEADER_FORMAT, header)
        if payload_len > MAX_MESSAGE_SIZE:
            err = f"Message exceeds maximum size: {payload_len} > {MAX_MESSAGE_SIZE}"
            raise ValueError(err)
        payload = _recv_exact(sock, payload_len)
        if payload is None:
            return None
        return message_from_dict(json.loads(payload))
    except TimeoutError:
        return None
    finally:
        sock.settimeout(prev_timeout)


def _recv_exact(sock: socket.socket, n: int) -> bytes | None:
    """Read exactly n bytes from a socket. Returns None on disconnect."""
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            if len(buf) == 0:
                return None
            msg = "Connection closed mid-message"
            raise ConnectionError(msg)
        buf.extend(chunk)
    return bytes(buf)
