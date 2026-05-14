"""Message dataclasses and serialization for the Lux display protocol."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal, Self, cast

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
    "MessageRegistry",
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
# Codec type aliases
# ---------------------------------------------------------------------------

_Serializer = Callable[..., dict[str, Any]]
_Deserializer = Callable[[dict[str, Any]], Any]

_CodecEntry = tuple[type, _Serializer, _Deserializer]

# ---------------------------------------------------------------------------
# MessageRegistry — dispatch table mapping type strings to codec pairs
# ---------------------------------------------------------------------------


class MessageRegistry:
    """Dispatch table mapping type strings to codec pairs.

    Instance-based so tests can create isolated registries without
    polluting the module-level default.  The production registry is
    a module-level instance populated at import time.
    """

    _codecs: dict[str, _CodecEntry]
    _serializers: dict[type, _Serializer]

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._codecs = {}
        self._serializers = {}
        return self

    def register(
        self,
        type_str: str,
        cls: type,
        to_fn: _Serializer,
        from_fn: _Deserializer,
    ) -> None:
        """Register a message type's codec pair."""
        if type_str in self._codecs:
            msg = f"Duplicate message registration: {type_str!r}"
            raise ValueError(msg)
        self._codecs[type_str] = (cls, to_fn, from_fn)
        self._serializers[cls] = to_fn

    def to_dict(self, msg: Message) -> dict[str, Any]:
        """Serialize a Message to a JSON-compatible dict."""
        serializer = self._serializers.get(type(msg))
        if serializer is not None:
            return serializer(msg)
        err = f"Unknown message type: {type(msg)}"
        raise TypeError(err)

    def from_dict(self, d: dict[str, Any]) -> Message:
        """Deserialize a JSON dict to the appropriate Message."""
        msg_type = d.get("type", "")
        codec = self._codecs.get(msg_type)
        if codec is not None:
            _, _, from_fn = codec
            return cast("Message", from_fn(d))
        if not isinstance(msg_type, str) or not msg_type:
            err = "Message missing or invalid 'type' field"
            raise ValueError(err)
        return UnknownMessage(raw_type=msg_type, data=d)

    @property
    def registered_types(self) -> frozenset[str]:
        """Return the set of registered type strings."""
        return frozenset(self._codecs)

    @property
    def serializers(self) -> dict[type, _Serializer]:
        """Return the serializer mapping (read-only copy)."""
        return dict(self._serializers)


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _ts_dict(msg_type: str, ts: float | None) -> dict[str, Any]:
    d: dict[str, Any] = {"type": msg_type}
    if ts is not None:
        d["ts"] = ts
    return d


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


# ---------------------------------------------------------------------------
# Codec functions — serializers
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


def _ready_to_dict(m: ReadyMessage) -> dict[str, Any]:
    d: dict[str, Any] = {"type": m.type, "version": m.version}
    if m.capabilities:
        d["capabilities"] = m.capabilities
    return d


def _ack_to_dict(m: AckMessage) -> dict[str, Any]:
    d: dict[str, Any] = {"type": m.type, "scene_id": m.scene_id}
    if m.ts is not None:
        d["ts"] = m.ts
    if m.error is not None:
        d["error"] = m.error
    return d


def _pong_to_dict(m: PongMessage) -> dict[str, Any]:
    d = _ts_dict(m.type, m.ts)
    if m.display_ts is not None:
        d["display_ts"] = m.display_ts
    return d


def _register_menu_to_dict(m: RegisterMenuMessage) -> dict[str, Any]:
    return {"type": m.type, "items": m.items}


def _introspect_response_to_dict(m: IntrospectResponse) -> dict[str, Any]:
    d: dict[str, Any] = {
        "type": m.type,
        "scene_id": m.scene_id,
        "elements": m.elements,
    }
    if m.error is not None:
        d["error"] = m.error
    return d


def _screenshot_response_to_dict(m: ScreenshotResponse) -> dict[str, Any]:
    d: dict[str, Any] = {"type": m.type, "path": m.path}
    if m.error is not None:
        d["error"] = m.error
    return d


def _query_request_to_dict(m: QueryRequest) -> dict[str, Any]:
    d: dict[str, Any] = {"type": m.type, "method": m.method}
    if m.params:
        d["params"] = m.params
    return d


def _query_response_to_dict(m: QueryResponse) -> dict[str, Any]:
    d: dict[str, Any] = {"type": m.type, "method": m.method, "result": m.result}
    if m.error is not None:
        d["error"] = m.error
    return d


def _connect_to_dict(m: ConnectMessage) -> dict[str, Any]:
    return {"type": m.type, "name": m.name}


def _clear_to_dict(m: ClearMessage) -> dict[str, Any]:
    return {"type": m.type}


def _ping_to_dict(m: PingMessage) -> dict[str, Any]:
    return _ts_dict(m.type, m.ts)


def _menu_to_dict(m: MenuMessage) -> dict[str, Any]:
    return {"type": m.type, "menus": m.menus}


def _theme_to_dict(m: ThemeMessage) -> dict[str, Any]:
    return {"type": m.type, "theme": m.theme}


def _introspect_request_to_dict(m: IntrospectRequest) -> dict[str, Any]:
    return {"type": m.type, "scene_id": m.scene_id}


def _list_scenes_request_to_dict(m: ListScenesRequest) -> dict[str, Any]:
    return {"type": m.type}


def _list_scenes_response_to_dict(m: ListScenesResponse) -> dict[str, Any]:
    return {"type": m.type, "scenes": m.scenes, "frames": m.frames}


def _screenshot_request_to_dict(m: ScreenshotRequest) -> dict[str, Any]:
    return {"type": m.type}


def _unknown_to_dict(m: UnknownMessage) -> dict[str, Any]:
    d = dict(m.data)
    d["type"] = m.raw_type
    return d


# ---------------------------------------------------------------------------
# Codec functions — deserializers
# ---------------------------------------------------------------------------


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


def _interaction_from_dict(d: dict[str, Any]) -> InteractionMessage:
    return InteractionMessage(
        element_id=d["element_id"],
        action=d["action"],
        ts=d.get("ts"),
        value=d.get("value"),
        scene_id=d.get("scene_id"),
    )


def _connect_from_dict(d: dict[str, Any]) -> ConnectMessage:
    name = d.get("name")
    if not isinstance(name, str) or not name.strip():
        err = "ConnectMessage missing or invalid 'name' field"
        raise ValueError(err)
    return ConnectMessage(name=name)


def _register_menu_from_dict(d: dict[str, Any]) -> RegisterMenuMessage:
    raw = d.get("items")
    raw_items = cast("list[Any]", raw) if isinstance(raw, list) else []  # type: ignore[redundant-cast]
    return RegisterMenuMessage(items=[e for e in raw_items if isinstance(e, dict)])


def _introspect_response_from_dict(d: dict[str, Any]) -> IntrospectResponse:
    return IntrospectResponse(
        scene_id=d["scene_id"],
        elements=d.get("elements", []),
        error=d.get("error"),
    )


def _screenshot_response_from_dict(d: dict[str, Any]) -> ScreenshotResponse:
    return ScreenshotResponse(
        path=d.get("path", ""),
        error=d.get("error"),
    )


def _ready_from_dict(d: dict[str, Any]) -> ReadyMessage:
    return ReadyMessage(
        version=d.get("version", PROTOCOL_VERSION),
        capabilities=d.get("capabilities", []),
    )


def _ack_from_dict(d: dict[str, Any]) -> AckMessage:
    return AckMessage(scene_id=d["scene_id"], ts=d.get("ts"), error=d.get("error"))


def _pong_from_dict(d: dict[str, Any]) -> PongMessage:
    return PongMessage(ts=d.get("ts"), display_ts=d.get("display_ts"))


def _query_request_from_dict(d: dict[str, Any]) -> QueryRequest:
    return QueryRequest(method=d["method"], params=d.get("params", {}))


def _query_response_from_dict(d: dict[str, Any]) -> QueryResponse:
    return QueryResponse(
        method=d["method"],
        result=d.get("result", {}),
        error=d.get("error"),
    )


def _clear_from_dict(_d: dict[str, Any]) -> ClearMessage:
    return ClearMessage()


def _ping_from_dict(d: dict[str, Any]) -> PingMessage:
    return PingMessage(ts=d.get("ts"))


def _menu_from_dict(d: dict[str, Any]) -> MenuMessage:
    return MenuMessage(menus=d.get("menus", []))


def _theme_from_dict(d: dict[str, Any]) -> ThemeMessage:
    return ThemeMessage(theme=d["theme"])


def _introspect_request_from_dict(d: dict[str, Any]) -> IntrospectRequest:
    return IntrospectRequest(scene_id=d["scene_id"])


def _list_scenes_request_from_dict(_d: dict[str, Any]) -> ListScenesRequest:
    return ListScenesRequest()


def _list_scenes_response_from_dict(d: dict[str, Any]) -> ListScenesResponse:
    return ListScenesResponse(scenes=d.get("scenes", []), frames=d.get("frames", []))


def _screenshot_request_from_dict(_d: dict[str, Any]) -> ScreenshotRequest:
    return ScreenshotRequest()


def _unknown_from_dict(d: dict[str, Any]) -> UnknownMessage:
    return UnknownMessage(raw_type=d.get("type", "unknown"), data=d)


# ---------------------------------------------------------------------------
# Default registry — populated at import time
# ---------------------------------------------------------------------------

_registry = MessageRegistry()

_registry.register("scene", SceneMessage, _scene_to_dict, _scene_from_dict)
_registry.register("update", UpdateMessage, _update_to_dict, _update_from_dict)
_registry.register(
    "interaction", InteractionMessage, _interaction_to_dict, _interaction_from_dict
)
_registry.register("connect", ConnectMessage, _connect_to_dict, _connect_from_dict)
_registry.register(
    "register_menu",
    RegisterMenuMessage,
    _register_menu_to_dict,
    _register_menu_from_dict,
)
_registry.register(
    "introspect_response",
    IntrospectResponse,
    _introspect_response_to_dict,
    _introspect_response_from_dict,
)
_registry.register(
    "screenshot_response",
    ScreenshotResponse,
    _screenshot_response_to_dict,
    _screenshot_response_from_dict,
)
_registry.register(
    "query_request", QueryRequest, _query_request_to_dict, _query_request_from_dict
)
_registry.register(
    "query_response", QueryResponse, _query_response_to_dict, _query_response_from_dict
)
_registry.register("ready", ReadyMessage, _ready_to_dict, _ready_from_dict)
_registry.register("ack", AckMessage, _ack_to_dict, _ack_from_dict)
_registry.register("pong", PongMessage, _pong_to_dict, _pong_from_dict)
_registry.register("clear", ClearMessage, _clear_to_dict, _clear_from_dict)
_registry.register("ping", PingMessage, _ping_to_dict, _ping_from_dict)
_registry.register("menu", MenuMessage, _menu_to_dict, _menu_from_dict)
_registry.register("theme", ThemeMessage, _theme_to_dict, _theme_from_dict)
_registry.register(
    "introspect_request",
    IntrospectRequest,
    _introspect_request_to_dict,
    _introspect_request_from_dict,
)
_registry.register(
    "list_scenes_request",
    ListScenesRequest,
    _list_scenes_request_to_dict,
    _list_scenes_request_from_dict,
)
_registry.register(
    "list_scenes_response",
    ListScenesResponse,
    _list_scenes_response_to_dict,
    _list_scenes_response_from_dict,
)
_registry.register(
    "screenshot_request",
    ScreenshotRequest,
    _screenshot_request_to_dict,
    _screenshot_request_from_dict,
)
_registry.register("unknown", UnknownMessage, _unknown_to_dict, _unknown_from_dict)

# Legacy alias — populated from the registry for any external consumer
_MESSAGE_SERIALIZERS: dict[type, _Serializer] = dict(_registry.serializers)

# ---------------------------------------------------------------------------
# Public API (unchanged signatures)
# ---------------------------------------------------------------------------


def message_to_dict(msg: Message) -> dict[str, Any]:
    """Serialize a Message dataclass to a JSON-compatible dict."""
    return _registry.to_dict(msg)


def message_from_dict(d: dict[str, Any]) -> Message:
    """Deserialize a JSON dict to the appropriate Message dataclass."""
    return _registry.from_dict(d)
