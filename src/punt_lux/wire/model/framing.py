"""Length-prefixed JSON framing and blocking socket primitives."""

from __future__ import annotations

import json
import socket
import struct
from typing import TYPE_CHECKING, Any

from punt_lux.wire.model.frame_header import (
    HEADER_FORMAT,
    HEADER_SIZE,
    MAX_MESSAGE_SIZE,
)
from punt_lux.wire.model.json_payload import JsonPayload
from punt_lux.wire.model.messages import Message, message_from_dict, message_to_dict

if TYPE_CHECKING:
    from punt_lux.wire.model.messages.wire_vocabulary import WireVocabulary

__all__ = [
    "decode_frame",
    "encode_frame",
    "encode_message",
    "recv_message",
    "send_message",
]


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
    raw = JsonPayload(data[HEADER_SIZE : HEADER_SIZE + length]).as_object()
    return raw, data[HEADER_SIZE + length :]


def send_message(sock: socket.socket, msg: Message) -> None:
    """Send a framed message over a blocking socket."""
    sock.sendall(encode_message(msg))


def recv_message(
    sock: socket.socket, vocabulary: WireVocabulary, timeout: float = 5.0
) -> Message | None:
    """Receive a single framed message of a kind ``vocabulary`` admits.

    Returns None on timeout. A frame of any other kind raises ``ValueError``
    before it is decoded.
    """
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
        raw = JsonPayload(payload).as_object()
        vocabulary.require(raw.get("type"))
        return message_from_dict(raw)
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
