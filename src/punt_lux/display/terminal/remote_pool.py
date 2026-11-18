"""One Display connection and its terminal replicas, with asynchronous attach."""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Self

from punt_lux.display.terminal.remote import RemoteSession
from punt_lux.protocol.pty.control import WIRE_VERSION, ControlCodec
from punt_lux.protocol.pty.frames import Frame, FrameKind
from punt_lux.protocol.pty.hello import HelloRequest
from punt_lux.protocol.pty.replies import FailureReply, ReplyCodec
from punt_lux.ptyd.snapshot import snapshot_version
from punt_lux.terminal.connection import TerminalConnection


class RemotePool:
    _path: Path
    _sessions: dict[str, RemoteSession]
    _channels: dict[int, RemoteSession]
    _pending: dict[int, RemoteSession]
    _connection: TerminalConnection | None
    _ready: bool
    _next_id: int
    _hello_id: int
    _retry_at: float
    _last_output_at: float

    def __new__(cls, path: Path) -> Self:
        self = super().__new__(cls)
        self._path = path
        self._sessions, self._channels, self._pending = {}, {}, {}
        self._connection = None
        self._ready = False
        self._next_id = 1
        self._hello_id = 0
        self._retry_at = self._last_output_at = 0
        return self

    @classmethod
    def default(cls) -> Self:
        path = Path(
            os.environ.get(
                "LUX_PTY_SOCKET", str(Path.home() / ".punt-labs/lux/pty/luxd-pty.sock")
            )
        )
        return cls(path)

    @property
    def last_output_at(self) -> float:
        return self._last_output_at

    def get(self, name: str, command: str) -> RemoteSession:
        existing = self._sessions.get(name)
        if existing is not None:
            return existing
        session = RemoteSession(name, command, self.send)
        self._sessions[name] = session
        if self._ready:
            self._attach(session)
        return session

    def pump(self, budget_s: float = 0.003) -> bool:
        if not self._sessions:
            return False
        try:
            self._ensure_connection()
            if self._connection is None:
                return False
            frames = self._connection.pump(budget_s)
            for frame in frames:
                self._receive(frame)
            if frames:
                self._last_output_at = time.monotonic()
            return bool(frames)
        except (OSError, EOFError, ValueError, RuntimeError, BufferError) as error:
            self._disconnect(str(error))
            return False

    def send(self, frame: Frame) -> None:
        if self._connection is not None:
            try:
                self._connection.queue(frame)
            except (OSError, BufferError) as error:
                self._disconnect(str(error))

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
        self._connection = None
        self._ready = False
        for session in self._sessions.values():
            session.close()
        self._sessions.clear()
        self._channels.clear()
        self._pending.clear()

    def _ensure_connection(self) -> None:
        if self._connection is not None or time.monotonic() < self._retry_at:
            return
        self._connection = TerminalConnection(self._path)
        self._hello_id = self._id()
        hello = HelloRequest(self._hello_id, WIRE_VERSION, snapshot_version())
        self.send(Frame(0, FrameKind.DATA, ControlCodec.encode(hello)))

    def _attach(self, session: RemoteSession) -> None:
        request_id = self._id()
        self._pending[request_id] = session
        request = session.request(request_id)
        self.send(Frame(0, FrameKind.DATA, ControlCodec.encode(request)))

    def _receive(self, frame: Frame) -> None:
        if frame.channel == 0:
            self._reply(frame.payload)
            return
        session = self._channels.get(frame.channel)
        if session is None:
            raise ValueError("unexpected terminal channel")
        session.receive(frame)
        if frame.kind is FrameKind.CLOSE:
            self._channels.pop(frame.channel)

    def _reply(self, data: bytes) -> None:
        reply = ReplyCodec.decode(data)
        if reply.request_id == self._hello_id:
            if isinstance(reply, FailureReply):
                raise ConnectionError(reply.error)
            self._ready = True
            for session in self._sessions.values():
                self._attach(session)
            return
        pending = self._pending.pop(reply.request_id, None)
        if pending is None:
            raise ValueError("unexpected terminal reply id")
        if isinstance(reply, FailureReply):
            pending.fail(reply.error)
            return
        pending.begin(dict(reply.result))
        if pending.channel in self._channels:
            raise ValueError("duplicate terminal channel")
        self._channels[pending.channel] = pending

    def _id(self) -> int:
        value = self._next_id
        self._next_id += 1
        return value

    def _disconnect(self, message: str) -> None:
        if self._connection is not None:
            self._connection.close()
        self._connection = None
        self._ready = False
        self._channels.clear()
        self._pending.clear()
        self._retry_at = time.monotonic() + 1
        for session in self._sessions.values():
            session.disconnected(message)
