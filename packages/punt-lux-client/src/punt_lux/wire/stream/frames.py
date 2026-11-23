"""Bounded binary frames for terminal attachments over a stream socket.

Header: channel (uint32 LE), kind (uint8), payload length (uint32 LE).
A socket read is not a frame: the decoder accepts arbitrary fragmentation
and multiple frames per read. Callers read at most ``MAX_READ_BYTES`` at once.
Protocol errors poison the decoder; the owning connection must then close.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import ClassVar, Self

from punt_lux.wire.stream.frame_types import FrameError, FrameKind

__all__ = [
    "MAX_PAYLOAD_BYTES",
    "MAX_READ_BYTES",
    "Frame",
    "FrameDecoder",
    "FrameError",
    "FrameKind",
]

MAX_PAYLOAD_BYTES = 1024 * 1024
MAX_READ_BYTES = 64 * 1024
_MAX_CHANNEL = (1 << 32) - 1
_HEADER = struct.Struct("<IBI")


@dataclass(frozen=True, slots=True)
class Frame:
    """One validated transport frame, owning its immutable payload."""

    channel: int
    kind: FrameKind
    payload: bytes
    HEADER_BYTES: ClassVar[int] = _HEADER.size

    def __post_init__(self) -> None:
        self._validate_channel()
        if type(self.kind) is not FrameKind:
            raise FrameError("frame kind is not a negotiated version-one kind")
        if type(self.payload) is not bytes:
            raise FrameError("payload must be immutable bytes")
        if len(self.payload) > MAX_PAYLOAD_BYTES:
            raise FrameError("frame payload exceeds the size limit")

    def _validate_channel(self) -> None:
        """Do not let bools or floats pass the integer wire boundary."""
        if type(self.channel) is not int or not 0 <= self.channel <= _MAX_CHANNEL:
            raise FrameError("channel does not fit uint32")

    def encode(self) -> bytes:
        """Encode this frame, without escaping or copying each payload byte."""
        return _HEADER.pack(self.channel, self.kind, len(self.payload)) + self.payload

    @classmethod
    def from_buffer(cls, data: bytearray) -> Self | None:
        """Remove and return one complete frame, or wait for more bytes.

        A declared oversize length or unknown kind fails as soon as the header
        arrives; the decoder never waits for an invalid payload to arrive.
        """
        if len(data) < cls.HEADER_BYTES:
            return None
        channel, raw_kind, length = _HEADER.unpack_from(data)
        if length > MAX_PAYLOAD_BYTES:
            raise FrameError("declared payload exceeds the size limit")
        try:
            kind = FrameKind(raw_kind)
        except ValueError as error:
            raise FrameError(f"unknown frame kind {raw_kind}") from error
        end = cls.HEADER_BYTES + length
        if len(data) < end:
            return None
        payload = bytes(data[cls.HEADER_BYTES : end])
        del data[:end]
        return cls(channel, kind, payload)


class FrameDecoder:
    """Incrementally decode one connection's bounded receive buffer."""

    _pending: bytearray
    _failed: bool

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._pending = bytearray()
        self._failed = False
        return self

    @property
    def pending_bytes(self) -> int:
        """Bytes waiting for the remainder of one frame."""
        return len(self._pending)

    def feed(self, data: bytes) -> list[Frame]:
        """Consume one bounded socket read and return every complete frame."""
        if self._failed:
            raise FrameError("decoder cannot be reused after a protocol error")
        try:
            if len(data) > MAX_READ_BYTES:
                raise FrameError("socket read exceeds the receive limit")
            self._pending.extend(data)
            frames: list[Frame] = []
            while (frame := Frame.from_buffer(self._pending)) is not None:
                frames.append(frame)
            return frames
        except FrameError:
            self._pending.clear()
            self._failed = True
            raise

    def finish(self) -> None:
        """Validate EOF; a truncated header or payload is a protocol error."""
        if self._failed:
            raise FrameError("decoder cannot be reused after a protocol error")
        if self._pending:
            self._pending.clear()
            self._failed = True
            raise FrameError("connection ended inside a frame")
