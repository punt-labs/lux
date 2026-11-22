"""Bounded blocking test client; production Display transport comes next."""

from __future__ import annotations

import socket
import struct
import time
from pathlib import Path
from typing import Self

from punt_lux.protocol.pty.control import ControlCodec, ControlRequest
from punt_lux.protocol.pty.frames import MAX_READ_BYTES, Frame, FrameDecoder, FrameKind
from punt_lux.protocol.pty.replies import Reply, ReplyCodec
from punt_lux.terminal.output import SessionSnapshot


class WireClient:
    _socket: socket.socket
    _decoder: FrameDecoder
    _frames: list[Frame]
    _auto_credit: bool

    def __new__(cls, path: Path, *, auto_credit: bool = True) -> Self:
        self = super().__new__(cls)
        self._socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._socket.settimeout(4)
        self._socket.connect(str(path))
        self._decoder = FrameDecoder()
        self._frames = []
        self._auto_credit = auto_credit
        return self

    def enable_credit(self) -> None:
        self._auto_credit = True

    def close(self) -> None:
        self._socket.close()

    def request(self, request: ControlRequest) -> Reply:
        self.send(Frame(0, FrameKind.DATA, ControlCodec.encode(request)))
        frame = self.next(0)
        assert frame.kind is FrameKind.DATA
        reply = ReplyCodec.decode(frame.payload)
        assert reply.request_id == request.request_id
        return reply

    def send(self, frame: Frame) -> None:
        self._socket.sendall(frame.encode())

    def next(self, channel: int) -> Frame:
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            for index, frame in enumerate(self._frames):
                if frame.channel == channel:
                    value = self._frames.pop(index)
                    self._acknowledge(value)
                    return value
            data = self._socket.recv(MAX_READ_BYTES)
            if not data:
                raise EOFError("daemon closed the test connection")
            self._frames.extend(self._decoder.feed(data))
        raise TimeoutError("daemon frame deadline exceeded")

    def snapshot(self, metadata: dict[str, object]) -> tuple[int, SessionSnapshot]:
        channel, size = metadata["channel"], metadata["size"]
        assert isinstance(channel, int) and isinstance(size, int)
        data = bytearray()
        while len(data) < size:
            frame = self.next(channel)
            assert frame.kind is FrameKind.SNAPSHOT
            data.extend(frame.payload)
        return channel, SessionSnapshot.from_dict(metadata, bytes(data))

    def _acknowledge(self, frame: Frame) -> None:
        if not self._auto_credit or frame.channel == 0:
            return
        if frame.kind in (FrameKind.DATA, FrameKind.SNAPSHOT):
            self.send(
                Frame(
                    frame.channel,
                    FrameKind.CREDIT,
                    struct.pack("<I", len(frame.payload)),
                )
            )
        elif frame.kind is FrameKind.CLOSE:
            self.send(Frame(frame.channel, FrameKind.CLOSE, b""))
