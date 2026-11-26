"""A one-connection daemon that answers hello, then replies with scripted payloads."""

from __future__ import annotations

import socket
import tempfile
import threading
from pathlib import Path
from types import TracebackType
from typing import Self

from punt_lux.wire.stream.frames import MAX_READ_BYTES, Frame, FrameKind
from punt_lux.wire.stream.replies import ReplyCodec, SuccessReply


class ScriptedDaemon:
    """Serve ``replies`` in order after the hello reply, one per request.

    ``raw`` bytes, when given, answer the first request instead, unframed.
    """

    _replies: tuple[bytes, ...]
    _raw: bytes
    _directory: tempfile.TemporaryDirectory[str]
    _server: socket.socket
    _thread: threading.Thread

    def __new__(cls, *replies: bytes, raw: bytes = b"") -> Self:
        self = super().__new__(cls)
        self._replies, self._raw = replies, raw
        self._directory = tempfile.TemporaryDirectory(prefix="lxscr-", dir="/tmp")
        self._server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._server.bind(str(self.path))
        self._server.listen(1)
        self._thread = threading.Thread(target=self._serve, daemon=True)
        return self

    @property
    def path(self) -> Path:
        return Path(self._directory.name) / "pty.sock"

    def __enter__(self) -> Self:
        self._thread.start()
        return self

    def __exit__(
        self,
        _type: type[BaseException] | None,
        _error: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        self._thread.join(timeout=5)
        self._server.close()
        self._directory.cleanup()

    def _serve(self) -> None:
        connection, _ = self._server.accept()
        with connection:
            hello = ReplyCodec.encode(SuccessReply(1, {}))
            for payload in (hello, *self._replies):
                if not connection.recv(MAX_READ_BYTES):
                    return
                connection.sendall(Frame(0, FrameKind.DATA, payload).encode())
                if self._raw and payload is hello:
                    if connection.recv(MAX_READ_BYTES):
                        connection.sendall(self._raw)
                    return
