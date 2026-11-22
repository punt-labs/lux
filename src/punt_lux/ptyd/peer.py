"""One authenticated connection; detaching it never closes a terminal session."""

from __future__ import annotations

import socket
from typing import Self

from punt_lux.protocol.pty.frames import MAX_READ_BYTES, Frame, FrameDecoder
from punt_lux.socket_writer import SocketWriter


class Peer:
    """Nonblocking frame IO and handshake state for one viewer."""

    _socket: socket.socket
    _decoder: FrameDecoder
    _writer: SocketWriter
    _ready: bool
    _closed: bool

    def __new__(cls, sock: socket.socket) -> Self:
        self = super().__new__(cls)
        self._socket = sock
        sock.settimeout(0.0)
        self._decoder = FrameDecoder()
        self._writer = SocketWriter()
        self._ready = False
        self._closed = False
        return self

    @property
    def socket(self) -> socket.socket:
        return self._socket

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def ready(self) -> bool:
        return self._ready and not self._closed

    @property
    def wants_write(self) -> bool:
        return self._writer.pending_bytes > 0

    def mark_ready(self) -> None:
        self._ready = True

    def receive(self) -> list[Frame]:
        try:
            data = self._socket.recv(MAX_READ_BYTES)
        except BlockingIOError:
            return []
        if not data:
            self._decoder.finish()
            raise EOFError("viewer disconnected")
        return self._decoder.feed(data)

    def queue(self, frame: Frame) -> None:
        if self._closed:
            raise ConnectionError("viewer is closed")
        self._writer.append(frame.encode())

    def flush(self) -> None:
        self._writer.flush(self._socket)

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._socket.close()
            self._writer.clear()
