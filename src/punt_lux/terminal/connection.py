"""Nonblocking, authenticated local transport for a terminal viewer."""

from __future__ import annotations

import errno
import select
import socket
import time
from pathlib import Path
from typing import Self

from punt_lux.protocol.pty.frames import MAX_READ_BYTES, Frame, FrameDecoder
from punt_lux.ptyd.credentials import PeerCredentials
from punt_lux.ptyd.writer import WireWriter


class TerminalConnection:
    _socket: socket.socket
    _decoder: FrameDecoder
    _writer: WireWriter
    _connected: bool
    _closed: bool

    def __new__(cls, path: Path) -> Self:
        self = super().__new__(cls)
        self._socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._socket.settimeout(0.0)
        self._decoder = FrameDecoder()
        self._writer = WireWriter(limit=2 * 1024 * 1024)
        self._connected = False
        self._closed = False
        code = self._socket.connect_ex(str(path))
        if code not in (0, errno.EINPROGRESS, errno.EAGAIN, errno.EWOULDBLOCK):
            self.close()
            raise OSError(code, "cannot connect to luxd-pty; start the daemon")
        return self

    def queue(self, frame: Frame) -> None:
        if self._closed:
            raise ConnectionError("terminal connection is closed")
        self._writer.append(frame.encode())

    def pump(self, budget_s: float = 0.003) -> list[Frame]:
        if self._closed:
            return []
        if not self._connect_ready():
            return []
        self._writer.flush(self._socket)
        frames: list[Frame] = []
        deadline = time.monotonic() + budget_s
        received = 0
        while time.monotonic() < deadline and received < 256 * 1024:
            try:
                data = self._socket.recv(MAX_READ_BYTES)
            except BlockingIOError:
                break
            if not data:
                self._decoder.finish()
                raise EOFError("luxd-pty disconnected")
            received += len(data)
            frames.extend(self._decoder.feed(data))
        return frames

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._socket.close()
            self._writer.clear()

    def _connect_ready(self) -> bool:
        if self._connected:
            return True
        if not select.select([], [self._socket], [], 0)[1]:
            return False
        code = self._socket.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
        if code:
            raise OSError(code, "luxd-pty connection failed")
        PeerCredentials.require_same_user(self._socket)
        self._connected = True
        return True
