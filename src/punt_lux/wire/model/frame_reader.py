"""Incrementally read typed messages from a stream of frame bytes."""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING, Any, Self

from punt_lux.wire.model.frame_header import (
    HEADER_FORMAT,
    HEADER_SIZE,
    MAX_MESSAGE_SIZE,
)
from punt_lux.wire.model.json_payload import JsonPayload
from punt_lux.wire.model.messages import Message, message_from_dict

if TYPE_CHECKING:
    from collections.abc import Iterator

    from punt_lux.wire.model.messages.wire_vocabulary import WireVocabulary

__all__ = ["FrameReader"]


class FrameReader:
    """Buffer socket bytes and yield complete messages.

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

    def head(self, count: int) -> bytes:
        """Preview the leading buffered bytes of a malformed frame."""
        return bytes(self._buf[:count])

    def drain(self) -> list[dict[str, Any]]:
        """Extract all complete messages from the buffer as raw dicts."""
        messages: list[dict[str, Any]] = []
        while (framed := self._next_frame()) is not None:
            raw, total = framed
            del self._buf[:total]
            messages.append(raw)
        return messages

    def drain_typed(self, vocabulary: WireVocabulary) -> list[Message]:
        """Like drain(), but decodes only the kinds ``vocabulary`` admits.

        A frame of any other kind is skipped undecoded, so a newer peer's new
        message never breaks an older reader.
        """
        return [message_from_dict(d) for d in vocabulary.admitted(self.drain())]

    def iter_typed(self, vocabulary: WireVocabulary) -> Iterator[Message]:
        """Yield each complete message as it is decoded, one frame at a time.

        A frame whose raw ``type`` is not in ``vocabulary`` is refused before it is
        decoded. A frame that is refused or cannot be decoded raises and stays
        at the head of the buffer, so everything before it has already been
        yielded and :meth:`head` still shows what it began with.
        """
        while (framed := self._next_frame()) is not None:
            raw, total = framed
            vocabulary.require(raw.get("type"))
            message = message_from_dict(raw)
            del self._buf[:total]
            yield message

    def _next_frame(self) -> tuple[dict[str, Any], int] | None:
        """Parse the first complete frame without consuming it; ``None`` if partial."""
        if len(self._buf) < HEADER_SIZE:
            return None
        (payload_len,) = struct.unpack_from(HEADER_FORMAT, self._buf, 0)
        if payload_len > MAX_MESSAGE_SIZE:
            err = f"Message exceeds maximum size: {payload_len} > {MAX_MESSAGE_SIZE}"
            raise ValueError(err)
        total = HEADER_SIZE + payload_len
        if len(self._buf) < total:
            return None
        raw = JsonPayload(bytes(self._buf[HEADER_SIZE:total])).as_object()
        return raw, total
