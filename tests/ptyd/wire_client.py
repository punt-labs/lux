"""Bounded blocking test client; production Display transport comes next."""

from __future__ import annotations

import socket
import time
from pathlib import Path
from typing import Self

from punt_lux.protocol.pty.control import ControlCodec, ControlRequest
from punt_lux.protocol.pty.frames import MAX_READ_BYTES, Frame, FrameDecoder, FrameKind
from punt_lux.protocol.pty.replies import Reply, ReplyCodec
from punt_lux.ptyd.output import SessionSnapshot


class WireClient:
    _socket: socket.socket
    _decoder: FrameDecoder
    _frames: list[Frame]

    def __new__(cls, path: Path) -> Self:
        self = super().__new__(cls)
        self._socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._socket.settimeout(4)
        self._socket.connect(str(path))
        self._decoder = FrameDecoder()
        self._frames = []
        return self

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
                    return self._frames.pop(index)
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
