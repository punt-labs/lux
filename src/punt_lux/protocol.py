"""Wire protocol: length-prefixed JSON framing over Unix domain sockets."""

from __future__ import annotations

import json
import struct
from typing import Any

# Maximum message size: 16 MiB
MAX_MESSAGE_SIZE = 16 * 1024 * 1024


def encode_frame(payload: dict[str, Any]) -> bytes:
    """Encode a JSON message with 4-byte big-endian length prefix."""
    data = json.dumps(payload).encode("utf-8")
    if len(data) > MAX_MESSAGE_SIZE:
        msg = f"Message exceeds maximum size: {len(data)} > {MAX_MESSAGE_SIZE}"
        raise ValueError(msg)
    return struct.pack("!I", len(data)) + data


def decode_frame(data: bytes) -> tuple[dict[str, Any], bytes]:
    """Decode one length-prefixed frame from a byte buffer.

    Returns (decoded_message, remaining_bytes).
    """
    if len(data) < 4:
        msg = "Incomplete frame header"
        raise ValueError(msg)
    length = struct.unpack("!I", data[:4])[0]
    if length > MAX_MESSAGE_SIZE:
        msg = f"Message exceeds maximum size: {length} > {MAX_MESSAGE_SIZE}"
        raise ValueError(msg)
    if len(data) < 4 + length:
        msg = "Incomplete frame payload"
        raise ValueError(msg)
    payload: dict[str, Any] = json.loads(data[4 : 4 + length])
    return payload, data[4 + length :]
