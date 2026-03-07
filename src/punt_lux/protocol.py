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


Element = ImageElement | TextElement | ButtonElement | SeparatorElement

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


def _element_to_dict(elem: Element) -> dict[str, Any]:
    """Serialize an Element dataclass to a JSON-compatible dict."""
    if isinstance(elem, ImageElement):
        d: dict[str, Any] = {
            "kind": elem.kind,
            "id": elem.id,
            "path": elem.path,
            "data": elem.data,
            "format": elem.format,
            "alt": elem.alt,
            "width": elem.width,
            "height": elem.height,
        }
        return _strip_none(d)
    if isinstance(elem, TextElement):
        return _strip_none(
            {
                "kind": elem.kind,
                "id": elem.id,
                "content": elem.content,
                "style": elem.style,
            }
        )
    if isinstance(elem, ButtonElement):
        d = {
            "kind": elem.kind,
            "id": elem.id,
            "label": elem.label,
            "action": elem.action,
        }
        if elem.disabled:
            d["disabled"] = True
        return _strip_none(d)
    # SeparatorElement
    d = {"kind": elem.kind}
    if elem.id is not None:
        d["id"] = elem.id
    return d


def element_from_dict(d: dict[str, Any]) -> Element:
    """Deserialize a dict to the appropriate Element dataclass.

    Accepts dicts matching this module's element schema or as supplied by
    MCP tool callers.  Missing ``content``/``label`` keys default to ``""``.
    """
    kind = d.get("kind", "text")
    if kind == "image":
        return ImageElement(
            id=d["id"],
            path=d.get("path"),
            data=d.get("data"),
            format=d.get("format"),
            alt=d.get("alt"),
            width=d.get("width"),
            height=d.get("height"),
        )
    if kind == "text":
        return TextElement(
            id=d["id"], content=d.get("content", ""), style=d.get("style")
        )
    if kind == "button":
        return ButtonElement(
            id=d["id"],
            label=d.get("label", ""),
            action=d.get("action"),
            disabled=d.get("disabled", False),
        )
    if kind == "separator":
        return SeparatorElement(id=d.get("id"))
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
