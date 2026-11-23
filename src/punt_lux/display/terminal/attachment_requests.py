"""Hello/attach correlation with bounded backoff for transient operation failures."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Self

from punt_lux.display.terminal.cancelled_attaches import CancelledAttaches
from punt_lux.display.terminal.remote import RemoteSession
from punt_lux.display.terminal.remote_phase import RemotePhase
from punt_lux.display.terminal.retry_schedule import RetrySchedule
from punt_lux.protocol.pty.control import WIRE_VERSION, ControlCodec
from punt_lux.protocol.pty.frames import Frame, FrameKind
from punt_lux.protocol.pty.hello import HelloRequest
from punt_lux.protocol.pty.replies import FailureReply, ReplyCodec
from punt_lux.terminal.snapshot import snapshot_version


class AttachmentRequests:
    _send: Callable[[Frame], None]
    _pending: dict[int, RemoteSession]
    _cancelled: CancelledAttaches
    _schedule: RetrySchedule
    _hello_id: int
    _ready: bool

    def __new__(
        cls, send: Callable[[Frame], None], released: Callable[[int], None]
    ) -> Self:
        self = super().__new__(cls)
        self._send = send
        self._pending = {}
        self._cancelled = CancelledAttaches(send, released)
        self._schedule = RetrySchedule()
        self._hello_id = 0
        self._ready = False
        return self

    @property
    def ready(self) -> bool:
        return self._ready

    def hello(self, request_id: int) -> None:
        self._hello_id = request_id
        request = HelloRequest(request_id, WIRE_VERSION, snapshot_version())
        self._send(Frame(0, FrameKind.DATA, ControlCodec.encode(request)))

    def attach(self, request_id: int, session: RemoteSession) -> None:
        """Ask the daemon to attach ``session``, or hold it behind a cancelled one.

        While a cancelled attach for the same name is unanswered, the daemon
        still holds (or is about to bind) that viewer and would refuse this one
        as a duplicate; the session is held and ``due`` offers it again once
        that reply has been read.
        """
        if session.phase in (RemotePhase.FAILED, RemotePhase.CLOSED):
            return
        if self._cancelled.outstanding(session.name):
            self._schedule.hold(session)
            return
        self._pending[request_id] = session
        request = session.request(request_id)
        self._send(Frame(0, FrameKind.DATA, ControlCodec.encode(request)))

    def due(self) -> tuple[RemoteSession, ...]:
        return self._schedule.due(time.monotonic(), self._cancelled.outstanding)

    def receive(self, data: bytes) -> RemoteSession | None:
        reply = ReplyCodec.decode(data)
        if reply.request_id == self._hello_id:
            if isinstance(reply, FailureReply):
                raise ConnectionError(reply.error)
            self._ready = True
            return None
        if self._cancelled.consume(reply):
            return None
        session = self._pending.pop(reply.request_id, None)
        if session is None:
            raise ValueError("unexpected terminal reply id")
        if isinstance(reply, FailureReply):
            self._failed(session, reply)
            return None
        self._schedule.succeeded(session)
        session.begin(dict(reply.result))
        return session

    def _failed(self, session: RemoteSession, reply: FailureReply) -> None:
        if not reply.retryable:
            session.fail(reply.error)
            return
        self._schedule.failed(session, time.monotonic())
        session.disconnected(reply.error)

    def forget(self, session: RemoteSession) -> None:
        """Cancel every pending request and retry held for a released replica.

        A cancelled request's reply may still arrive; ``receive`` recognizes it
        instead of treating it as a protocol error.
        """
        cancelled = {i: s.name for i, s in self._pending.items() if s is session}
        self._cancelled.add(cancelled)
        self._pending = {i: s for i, s in self._pending.items() if i not in cancelled}
        self._schedule.discard(session)

    def reset(self) -> None:
        self._ready = False
        self._pending.clear()
        self._cancelled.clear()
        self._schedule.clear()

    def disconnect(self, sessions: tuple[RemoteSession, ...], message: str) -> None:
        self.reset()
        for session in sessions:
            if session.phase not in (RemotePhase.FAILED, RemotePhase.CLOSED):
                session.disconnected(message)
