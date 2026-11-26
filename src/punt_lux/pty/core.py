"""Daemon-owned named sessions, independent of viewer and socket lifetimes."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

from punt_lux.pty.fault import SessionFault
from punt_lux.pty.live_sessions import LiveSessions
from punt_lux.pty.process_factory import ProcessCreator, ProcessFactory
from punt_lux.pty.process_retirement import ProcessRetirement
from punt_lux.pty.session_birth import SessionBirth

if TYPE_CHECKING:
    from punt_lux.pty.session import TerminalSession
    from punt_lux.terminal.output import OutputChunk
    from punt_lux.wire.stream.new_request import NewRequest


class SessionError(RuntimeError):
    """A named-session operation could not be completed."""


class SessionCore:
    """One authoritative map, with explicit session removal and bounded count."""

    _live: LiveSessions
    _pending: ProcessRetirement
    _birth: SessionBirth
    _limit: int

    def __new__(
        cls,
        factory: ProcessCreator = ProcessFactory.start,
        *,
        limit: int = 16,
    ) -> Self:
        if limit < 1:
            raise ValueError("session limit must be positive")
        self = super().__new__(cls)
        self._live = LiveSessions()
        self._pending = ProcessRetirement()
        self._birth = SessionBirth(factory, self._pending)
        self._limit = limit
        return self

    def create(self, request: NewRequest) -> TerminalSession:
        """Start a new session under a fresh id and a unique label."""
        if len(self._live) + len(self._pending) >= self._limit:
            raise SessionError("terminal session limit reached")
        session = self._birth.start(self._live.spec(request))
        self._live.add(session)
        return session

    def attach(self, name: str) -> TerminalSession:
        """Return the running session ``name``; resuming never starts a shell."""
        return self._live.running(name)

    @property
    def exited(self) -> tuple[TerminalSession, ...]:
        """Sessions whose program has ended and that are not yet removed."""
        return self._live.exited()

    def get(self, name: str) -> TerminalSession:
        try:
            return self._live.get(name)
        except KeyError as error:
            raise SessionError(f"unknown terminal session {name}") from error

    def pump(self) -> list[OutputChunk | SessionFault]:
        """Read every session regardless of which viewers are attached."""
        output: list[OutputChunk | SessionFault] = []
        self._pending.pump()
        for session in self._live:
            try:
                chunk = session.pump()
            except (OSError, RuntimeError, BufferError) as error:
                output.append(SessionFault(session.name, str(error)))
                continue
            if chunk.data:
                output.append(chunk)
        return output

    def resize(self, name: str, cols: int, rows: int) -> bool:
        """Resize ``name``; a removed session has no size left to change."""
        return name in self._live and self._live.get(name).resize(cols, rows)

    def write(self, name: str, data: bytes) -> None:
        """Send input to ``name``; input in flight for a removed one is dropped."""
        if name in self._live:
            self._live.get(name).write(data)

    def describe(self) -> list[dict[str, object]]:
        return [session.describe() for session in self._live] + self._pending.describe()

    def kill(self, name: str) -> None:
        """Stop IO now; retain process ownership until pump-driven cleanup finishes."""
        if self._pending.contains(name):
            self._pending.stop(name)
            return
        session = self.get(name)
        process = session.close()
        self._live.remove(name)
        self._pending.add(name, process)
        self._pending.stop(name)

    def close(self) -> None:
        """Attempt every session; keep failed closures tracked for a retry."""
        failures: list[Exception] = []
        for session in self._live:
            try:
                self.kill(session.name)
            except (OSError, RuntimeError) as error:
                failures.append(error)
        failures.extend(self._pending.close())
        if failures:
            raise ExceptionGroup("terminal session shutdown failed", failures)
