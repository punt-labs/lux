"""Message dataclasses and serialization for the Lux display protocol."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal, cast

from punt_lux.protocol.elements import (
    Element,
    Patch,
    _element_to_dict,
    _patch_from_dict,
    _patch_to_dict,
    _strip_none,
    element_from_dict,
)

__all__ = [
    "_MESSAGE_SERIALIZERS",
    "AckMessage",
    "ClearMessage",
    "ClientMessage",
    "ConnectMessage",
    "DisplayMessage",
    "InteractionMessage",
    "IntrospectRequest",
    "IntrospectResponse",
    "ListScenesRequest",
    "ListScenesResponse",
    "MenuMessage",
    "Message",
    "PingMessage",
    "PongMessage",
    "QueryRequest",
    "QueryResponse",
    "ReadyMessage",
    "RegisterMenuMessage",
    "SceneMessage",
    "ScreenshotRequest",
    "ScreenshotResponse",
    "ThemeMessage",
    "UnknownMessage",
    "UpdateMessage",
    "message_from_dict",
    "message_to_dict",
]

# ---------------------------------------------------------------------------
# Constants (imported at use site; duplicated here to avoid circular import)
# ---------------------------------------------------------------------------

PROTOCOL_VERSION = "0.1"

# ---------------------------------------------------------------------------
# Client -> Display messages
# ---------------------------------------------------------------------------


@dataclass
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


@dataclass
class IntrospectRequest:
    """Request the element tree for a scene."""

    scene_id: str
    type: Literal["introspect_request"] = "introspect_request"


@dataclass
class IntrospectResponse:
    """Response with the scene's element tree."""

    scene_id: str
    elements: list[dict[str, Any]] = field(
        default_factory=lambda: list[dict[str, Any]]()
    )
    type: Literal["introspect_response"] = "introspect_response"
    error: str | None = None


@dataclass
class ListScenesRequest:
    """Request the list of active scenes and frames."""

    type: Literal["list_scenes_request"] = "list_scenes_request"


@dataclass
class ListScenesResponse:
    """Response with active scenes and frames."""

    scenes: list[dict[str, Any]] = field(default_factory=lambda: list[dict[str, Any]]())
    frames: list[dict[str, Any]] = field(default_factory=lambda: list[dict[str, Any]]())
    type: Literal["list_scenes_response"] = "list_scenes_response"


@dataclass
class ScreenshotRequest:
    """Request a screenshot of the current display."""

    type: Literal["screenshot_request"] = "screenshot_request"


@dataclass
class ScreenshotResponse:
    """Response with path to the captured screenshot."""

    path: str = ""
    type: Literal["screenshot_response"] = "screenshot_response"
    error: str | None = None


@dataclass
class MenuMessage:
    """Set custom menus in the menu bar (agent-extensible)."""

    menus: list[dict[str, Any]]  # [{label, items: [{label, id, shortcut?, enabled?}]}]
    type: Literal["menu"] = "menu"


@dataclass
class ThemeMessage:
    """Set the display theme."""

    theme: str  # snake_case theme name (e.g. "imgui_colors_light")
    type: Literal["theme"] = "theme"


@dataclass
class RegisterMenuMessage:
    """Register menu items owned by this client.

    Additive: each client's items are merged into the Tools menu.
    Replaces any previous registration from the same client (socket).
    Automatically cleaned up on disconnect.
    """

    items: list[dict[str, Any]]  # [{label, id, shortcut?, enabled?, icon?}]
    type: Literal["register_menu"] = "register_menu"


@dataclass
class ConnectMessage:
    """Client identifies itself to the display server.

    Sent after receiving ``ReadyMessage``.  The *name* field is used for
    display attribution (e.g. frame titles, menu namespaces).  Sending
    again updates the name (idempotent).
    """

    name: str
    type: Literal["connect"] = "connect"


@dataclass
class QueryRequest:
    """Generic introspection/control request."""

    method: str
    params: dict[str, Any] = field(default_factory=lambda: dict[str, Any]())
    type: Literal["query_request"] = "query_request"


ClientMessage = (
    SceneMessage
    | UpdateMessage
    | ClearMessage
    | PingMessage
    | IntrospectRequest
    | ListScenesRequest
    | ScreenshotRequest
    | MenuMessage
    | ThemeMessage
    | RegisterMenuMessage
    | ConnectMessage
    | QueryRequest
)

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
    scene_id: str | None = None


@dataclass
class PongMessage:
    """Response to a ping."""

    type: Literal["pong"] = "pong"
    ts: float | None = None
    display_ts: float | None = None


@dataclass
class QueryResponse:
    """Generic introspection/control response."""

    method: str
    result: dict[str, Any] = field(default_factory=lambda: dict[str, Any]())
    type: Literal["query_response"] = "query_response"
    error: str | None = None


@dataclass
class UnknownMessage:
    """Passthrough for unrecognized message types.

    Allows forward compatibility: a client sending a message type that
    this version of the display doesn't understand won't be disconnected.
    The display can log and skip unknown messages instead of raising.
    """

    raw_type: str
    data: dict[str, Any] = field(default_factory=lambda: {})  # noqa: PIE807
    type: Literal["unknown"] = "unknown"


DisplayMessage = (
    ReadyMessage
    | AckMessage
    | InteractionMessage
    | PongMessage
    | IntrospectResponse
    | ListScenesResponse
    | ScreenshotResponse
    | QueryResponse
)
Message = ClientMessage | DisplayMessage | UnknownMessage

# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


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
    if msg.scene_id is not None:
        d["scene_id"] = msg.scene_id
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


def _register_serializers() -> None:  # noqa: C901
    _MESSAGE_SERIALIZERS[SceneMessage] = _scene_to_dict
    _MESSAGE_SERIALIZERS[UpdateMessage] = _update_to_dict
    _MESSAGE_SERIALIZERS[InteractionMessage] = _interaction_to_dict

    def _clear(m: ClearMessage) -> dict[str, Any]:
        return {"type": m.type}

    def _ping(m: PingMessage) -> dict[str, Any]:
        return _ts_dict(m.type, m.ts)

    _MESSAGE_SERIALIZERS[ClearMessage] = _clear
    _MESSAGE_SERIALIZERS[PingMessage] = _ping

    def _menu(m: MenuMessage) -> dict[str, Any]:
        return {"type": m.type, "menus": m.menus}

    _MESSAGE_SERIALIZERS[MenuMessage] = _menu

    def _theme(m: ThemeMessage) -> dict[str, Any]:
        return {"type": m.type, "theme": m.theme}

    _MESSAGE_SERIALIZERS[ThemeMessage] = _theme

    def _register_menu(m: RegisterMenuMessage) -> dict[str, Any]:
        return {"type": m.type, "items": m.items}

    _MESSAGE_SERIALIZERS[RegisterMenuMessage] = _register_menu

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

    def _introspect_req(m: IntrospectRequest) -> dict[str, Any]:
        return {"type": m.type, "scene_id": m.scene_id}

    _MESSAGE_SERIALIZERS[IntrospectRequest] = _introspect_req

    def _introspect_resp(m: IntrospectResponse) -> dict[str, Any]:
        d: dict[str, Any] = {
            "type": m.type,
            "scene_id": m.scene_id,
            "elements": m.elements,
        }
        if m.error is not None:
            d["error"] = m.error
        return d

    _MESSAGE_SERIALIZERS[IntrospectResponse] = _introspect_resp

    def _connect(m: ConnectMessage) -> dict[str, Any]:
        return {"type": m.type, "name": m.name}

    _MESSAGE_SERIALIZERS[ConnectMessage] = _connect

    def _list_scenes_req(m: ListScenesRequest) -> dict[str, Any]:
        return {"type": m.type}

    _MESSAGE_SERIALIZERS[ListScenesRequest] = _list_scenes_req

    def _list_scenes_resp(m: ListScenesResponse) -> dict[str, Any]:
        return {"type": m.type, "scenes": m.scenes, "frames": m.frames}

    _MESSAGE_SERIALIZERS[ListScenesResponse] = _list_scenes_resp

    def _screenshot_req(m: ScreenshotRequest) -> dict[str, Any]:
        return {"type": m.type}

    _MESSAGE_SERIALIZERS[ScreenshotRequest] = _screenshot_req

    def _screenshot_resp(m: ScreenshotResponse) -> dict[str, Any]:
        d: dict[str, Any] = {"type": m.type, "path": m.path}
        if m.error is not None:
            d["error"] = m.error
        return d

    _MESSAGE_SERIALIZERS[ScreenshotResponse] = _screenshot_resp

    def _query_req(m: QueryRequest) -> dict[str, Any]:
        d: dict[str, Any] = {"type": m.type, "method": m.method}
        if m.params:
            d["params"] = m.params
        return d

    _MESSAGE_SERIALIZERS[QueryRequest] = _query_req

    def _query_resp(m: QueryResponse) -> dict[str, Any]:
        d: dict[str, Any] = {"type": m.type, "method": m.method, "result": m.result}
        if m.error is not None:
            d["error"] = m.error
        return d

    _MESSAGE_SERIALIZERS[QueryResponse] = _query_resp

    def _unknown(m: UnknownMessage) -> dict[str, Any]:
        d = dict(m.data)
        d["type"] = m.raw_type
        return d

    _MESSAGE_SERIALIZERS[UnknownMessage] = _unknown


_register_serializers()


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


def message_from_dict(d: dict[str, Any]) -> Message:  # noqa: C901
    """Deserialize a JSON dict to the appropriate Message dataclass."""
    msg_type = d.get("type", "")

    if msg_type == "scene":
        elements = [element_from_dict(e) for e in d.get("elements", [])]
        return SceneMessage(
            id=d["id"],
            elements=elements,
            layout=d.get("layout", "single"),
            title=d.get("title"),
            frame_id=d.get("frame_id"),
            frame_title=d.get("frame_title"),
            frame_size=_parse_frame_size(d.get("frame_size")),
            frame_flags=(
                d["frame_flags"] if isinstance(d.get("frame_flags"), dict) else None
            ),
            frame_layout=(
                d["frame_layout"]
                if isinstance(d.get("frame_layout"), str)
                and d["frame_layout"] in ("tab", "stack")
                else None
            ),
        )
    if msg_type == "update":
        patches = [_patch_from_dict(p) for p in d.get("patches", [])]
        return UpdateMessage(scene_id=d["scene_id"], patches=patches)
    if msg_type == "clear":
        return ClearMessage()
    if msg_type == "menu":
        return MenuMessage(menus=d.get("menus", []))
    if msg_type == "theme":
        return ThemeMessage(theme=d["theme"])
    if msg_type == "register_menu":
        raw = d.get("items")
        raw_items = cast("list[Any]", raw) if isinstance(raw, list) else []  # type: ignore[redundant-cast]
        return RegisterMenuMessage(items=[e for e in raw_items if isinstance(e, dict)])
    if msg_type == "ping":
        return PingMessage(ts=d.get("ts"))
    if msg_type == "introspect_request":
        return IntrospectRequest(scene_id=d["scene_id"])
    if msg_type == "introspect_response":
        return IntrospectResponse(
            scene_id=d["scene_id"],
            elements=d.get("elements", []),
            error=d.get("error"),
        )
    if msg_type == "list_scenes_request":
        return ListScenesRequest()
    if msg_type == "list_scenes_response":
        return ListScenesResponse(
            scenes=d.get("scenes", []),
            frames=d.get("frames", []),
        )
    if msg_type == "screenshot_request":
        return ScreenshotRequest()
    if msg_type == "screenshot_response":
        return ScreenshotResponse(
            path=d.get("path", ""),
            error=d.get("error"),
        )
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
            scene_id=d.get("scene_id"),
        )
    if msg_type == "pong":
        return PongMessage(ts=d.get("ts"), display_ts=d.get("display_ts"))

    if msg_type == "connect":
        name = d.get("name")
        if not isinstance(name, str) or not name.strip():
            err = "ConnectMessage missing or invalid 'name' field"
            raise ValueError(err)
        return ConnectMessage(name=name)
    if msg_type == "query_request":
        return QueryRequest(method=d["method"], params=d.get("params", {}))
    if msg_type == "query_response":
        return QueryResponse(
            method=d["method"],
            result=d.get("result", {}),
            error=d.get("error"),
        )

    if not isinstance(msg_type, str) or not msg_type:
        err = "Message missing or invalid 'type' field"
        raise ValueError(err)

    return UnknownMessage(raw_type=msg_type, data=d)
