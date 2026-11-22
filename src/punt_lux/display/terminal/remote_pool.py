"""Connect Display directly to luxd-pty's local Unix socket.

LUX_PTY_SOCKET overrides ~/.punt-labs/lux/pty/luxd-pty.sock; Hub routing is the target.
"""

from __future__ import annotations

import os
import time
from itertools import count
from pathlib import Path
from typing import Self

from punt_lux.display.terminal.attachment_requests import AttachmentRequests
from punt_lux.display.terminal.idling_decision import IdlingDecision
from punt_lux.display.terminal.remote import RemoteSession
from punt_lux.protocol.pty.frames import Frame, FrameKind
from punt_lux.terminal.connection import TerminalConnection


class RemotePool:
    _path: Path
    _sessions: dict[str, RemoteSession]
    _channels: dict[int, RemoteSession]
    _requests: AttachmentRequests
    _connection: TerminalConnection | None
    _ids: count[int]
    _retry_at: float
    _last_output_at: float

    def __new__(cls, path: Path) -> Self:
        self = super().__new__(cls)
        self._path = path
        self._sessions, self._channels = {}, {}
        self._requests = AttachmentRequests(self.send)
        self._connection = None
        self._ids = count(1)
        self._retry_at = self._last_output_at = 0
        return self

    @classmethod
    def default(cls) -> Self:
        sock = Path.home() / ".punt-labs/lux/pty/luxd-pty.sock"
        return cls(Path(os.environ.get("LUX_PTY_SOCKET", sock)))

    def pump_frame(self) -> IdlingDecision:
        """Pump once and report what this frame saw of terminal output."""
        return IdlingDecision(
            busy=self.pump(0.006),
            has_live_session=self._has_live_session,
            quiet_for=time.monotonic() - self._last_output_at,
        )

    @property
    def _has_live_session(self) -> bool:
        now = time.monotonic()
        return any(s.pins_frame_rate(now) for s in self._sessions.values())

    def get(self, name: str, command: str) -> RemoteSession:
        if (existing := self._sessions.get(name)) is not None:
            return existing
        session = RemoteSession(name, command, self.send)
        self._sessions[name] = session
        if self._requests.ready:
            self._attach(session)
        return session

    def pump(self, budget_s: float = 0.003) -> bool:
        if not self._sessions:
            return False
        try:
            self._ensure_connection()
            if self._connection is None:
                return False
            for session in self._requests.due():
                self._attach(session)
            frames = self._connection.pump(budget_s)
            for frame in frames:
                self._receive(frame)
            if frames:
                self._last_output_at = time.monotonic()
            return bool(frames)
        except (OSError, EOFError, ValueError, RuntimeError, BufferError) as error:
            self._disconnect(f"{self._path}: {error}")
            return False

    def send(self, frame: Frame) -> None:
        if self._connection is not None:
            try:
                self._connection.queue(frame)
            except (OSError, BufferError) as error:
                self._disconnect(str(error))

    def close(self) -> None:
        self._drop_connection()
        self._requests.reset()
        for session in self._sessions.values():
            session.close()
        self._sessions.clear()
        self._channels.clear()

    def _attach(self, session: RemoteSession) -> None:
        self._requests.attach(next(self._ids), session)

    def _ensure_connection(self) -> None:
        if self._connection is not None or time.monotonic() < self._retry_at:
            return
        self._connection = TerminalConnection(self._path)
        self._requests.hello(next(self._ids))

    def _receive(self, frame: Frame) -> None:
        if frame.channel == 0:
            self._reply(frame.payload)
            return
        if (session := self._channels.get(frame.channel)) is None:
            raise ValueError("unexpected terminal channel")
        session.receive(frame)
        if frame.kind is FrameKind.CLOSE:
            self._channels.pop(frame.channel)

    def _reply(self, data: bytes) -> None:
        ready = self._requests.ready
        pending = self._requests.receive(data)
        if not ready and self._requests.ready:
            for session in self._sessions.values():
                self._attach(session)
        elif pending is not None:
            if pending.channel in self._channels:
                raise ValueError("duplicate terminal channel")
            self._channels[pending.channel] = pending

    def _drop_connection(self) -> None:
        if self._connection is not None:
            self._connection.close()
        self._connection = None

    def _disconnect(self, message: str) -> None:
        self._drop_connection()
        self._requests.disconnect(tuple(self._sessions.values()), message)
        self._channels.clear()
        self._retry_at = time.monotonic() + 1
