"""Nonblocking, authenticated local transport for a terminal viewer."""

from __future__ import annotations

import errno
import select
import socket
import time
from pathlib import Path
from typing import Self

from punt_lux.credentials import PeerCredentials
from punt_lux.socket_writer import SocketWriter
from punt_lux.wire.stream.frames import MAX_READ_BYTES, Frame, FrameDecoder


class TerminalConnection:
    _socket: socket.socket
    _decoder: FrameDecoder
    _writer: SocketWriter
    _connected: bool
    _closed: bool

    def __new__(cls, path: Path) -> Self:
        self = super().__new__(cls)
        self._socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._socket.settimeout(0.0)
        self._decoder = FrameDecoder()
        self._writer = SocketWriter(limit=2 * 1024 * 1024)
        self._connected = False
        self._closed = False
        code = self._socket.connect_ex(str(path))
        if code not in (0, errno.EINPROGRESS, errno.EAGAIN, errno.EWOULDBLOCK):
            self.close()
            raise OSError(code, "luxd-pty unavailable; enable it on this machine")
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

    def drain(self, timeout_s: float) -> None:
        """Send queued frames until none remain or ``timeout_s`` passes.

        Called before a deliberate close so input the user already typed still
        reaches the program. A peer that stops reading cannot hold the Display:
        the wait is bounded, and an error ends it.
        """
        if self._closed:
            return
        deadline = time.monotonic() + timeout_s
        try:
            while self._writer.pending_bytes and time.monotonic() < deadline:
                if not self._connect_ready():
                    select.select([], [self._socket], [], 0.01)
                    continue
                self._writer.flush(self._socket)
                if self._writer.pending_bytes:
                    select.select([], [self._socket], [], 0.01)
        except (OSError, ConnectionError):
            return

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
