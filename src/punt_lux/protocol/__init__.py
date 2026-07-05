"""Lux display protocol v0.1 — message types, serialization, and framing.

Used by both client (MCP server / library) and display (ImGui renderer).

Wire format: 4-byte big-endian uint32 (payload length) + UTF-8 JSON payload.
Maximum message size: 16 MiB.
"""

from __future__ import annotations

import json
import socket
import struct
from typing import Any, Self, cast

from punt_lux.protocol.elements import (
    ButtonElement,
    CheckboxElement,
    CollapsingHeaderElement,
    ColorPickerElement,
    ComboElement,
    DrawElement,
    Element,
    GroupElement,
    ImageElement,
    InputNumberElement,
    InputTextElement,
    LegacyGroupElement,
    MarkdownElement,
    ModalElement,
    Patch,
    PlotElement,
    ProgressElement,
    RadioElement,
    SelectableElement,
    SeparatorElement,
    SliderElement,
    SpinnerElement,
    TabBarElement,
    TableDetail,
    TableElement,
    TableFilter,
    TextElement,
    TreeElement,
    WindowElement,
    element_to_dict,
)
from punt_lux.protocol.messages import (
    PROTOCOL_VERSION,
    AckMessage,
    ClearMessage,
    ClientMessage,
    ConnectMessage,
    DisplayMessage,
    IntrospectRequest,
    IntrospectResponse,
    ListScenesRequest,
    ListScenesResponse,
    MenuMessage,
    Message,
    ObserverMessage,
    PingMessage,
    PongMessage,
    QueryRequest,
    QueryResponse,
    ReadyMessage,
    RegisterMenuMessage,
    RemoteEventHandlerInvocation,
    SceneMessage,
    ScreenshotRequest,
    ScreenshotResponse,
    ThemeMessage,
    UnknownMessage,
    UpdateMessage,
    message_from_dict,
    message_to_dict,
)

__all__ = [
    "HEADER_FORMAT",
    "HEADER_SIZE",
    "MAX_MESSAGE_SIZE",
    "PROTOCOL_VERSION",
    "AckMessage",
    "ButtonElement",
    "CheckboxElement",
    "ClearMessage",
    "ClientMessage",
    "CollapsingHeaderElement",
    "ColorPickerElement",
    "ComboElement",
    "ConnectMessage",
    "DisplayMessage",
    "DrawElement",
    "Element",
    "FrameReader",
    "GroupElement",
    "ImageElement",
    "InputNumberElement",
    "InputTextElement",
    "IntrospectRequest",
    "IntrospectResponse",
    "LegacyGroupElement",
    "ListScenesRequest",
    "ListScenesResponse",
    "MarkdownElement",
    "MenuMessage",
    "Message",
    "ModalElement",
    "ObserverMessage",
    "Patch",
    "PingMessage",
    "PlotElement",
    "PongMessage",
    "ProgressElement",
    "QueryRequest",
    "QueryResponse",
    "RadioElement",
    "ReadyMessage",
    "RegisterMenuMessage",
    "RemoteEventHandlerInvocation",
    "SceneMessage",
    "ScreenshotRequest",
    "ScreenshotResponse",
    "SelectableElement",
    "SeparatorElement",
    "SliderElement",
    "SpinnerElement",
    "TabBarElement",
    "TableDetail",
    "TableElement",
    "TableFilter",
    "TextElement",
    "ThemeMessage",
    "TreeElement",
    "UnknownMessage",
    "UpdateMessage",
    "WindowElement",
    "decode_frame",
    "element_to_dict",
    "encode_frame",
    "encode_message",
    "message_from_dict",
    "message_to_dict",
    "recv_message",
    "send_message",
]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_MESSAGE_SIZE = 16 * 1024 * 1024  # 16 MiB
HEADER_SIZE = 4
HEADER_FORMAT = "!I"  # big-endian uint32

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

    _buf: bytearray

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._buf = bytearray()
        return self

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
