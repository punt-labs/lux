"""Daemon-owned named sessions, independent of viewer and socket lifetimes."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

from punt_lux.protocol.pty.attach import AttachRequest
from punt_lux.ptyd.fault import SessionFault
from punt_lux.ptyd.process_factory import ProcessCreator, ProcessFactory
from punt_lux.ptyd.process_retirement import ProcessRetirement
from punt_lux.ptyd.session_birth import SessionBirth

if TYPE_CHECKING:
    from punt_lux.ptyd.output import OutputChunk
    from punt_lux.ptyd.session import TerminalSession


class SessionError(RuntimeError):
    """A named-session operation could not be completed."""


class SessionCore:
    """One authoritative map, with explicit session removal and bounded count."""

    _sessions: dict[str, TerminalSession]
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
        self._sessions = {}
        self._pending = ProcessRetirement()
        self._birth = SessionBirth(factory, self._pending)
        self._limit = limit
        return self

    def acquire(self, request: AttachRequest) -> TerminalSession:
        """Reattach to a running shell; respawn a fresh one once it has exited.

        A reconnect to a live program reuses its session so output and scrollback
        survive the viewer's absence. An *exited* session has no shell to reattach
        to, so the next attach retires the dead one and starts a new shell — the
        terminal is never stuck on a dead process with no way back to a prompt.
        """
        if self._pending.contains(request.session):
            raise SessionError("session is waiting for failed-start cleanup")
        existing = self._sessions.get(request.session)
        if existing is None:
            return self._start(request)
        if existing.ended:
            self.kill(request.session)  # retire the dead shell, then spawn fresh
            return self._start(request)
        self._check_command(request)
        return existing

    def _check_command(self, request: AttachRequest) -> None:
        command = self._sessions[request.session].command
        if request.command and request.command != command:
            raise ValueError("session already exists with another command")

    def _start(self, request: AttachRequest) -> TerminalSession:
        if len(self._sessions) + len(self._pending) >= self._limit:
            raise SessionError("terminal session limit reached")
        session = self._birth.start(request)
        self._sessions[request.session] = session
        return session

    def get(self, name: str) -> TerminalSession:
        try:
            return self._sessions[name]
        except KeyError as error:
            raise SessionError(f"unknown terminal session {name}") from error

    def pump(self) -> list[OutputChunk | SessionFault]:
        """Read every session regardless of which viewers are attached."""
        output: list[OutputChunk | SessionFault] = []
        self._pending.pump()
        for session in self._sessions.values():
            try:
                chunk = session.pump()
            except (OSError, RuntimeError, BufferError) as error:
                output.append(SessionFault(session.name, str(error)))
                continue
            if chunk.data:
                output.append(chunk)
        return output

    def resize(self, name: str, cols: int, rows: int) -> None:
        # Validate the same boundary as initial attachment.
        AttachRequest(1, name, cols=cols, rows=rows)
        self.get(name).resize(cols, rows)

    def describe(self) -> list[dict[str, object]]:
        return [
            session.describe() for session in self._sessions.values()
        ] + self._pending.describe()

    def kill(self, name: str) -> None:
        """Stop IO now; retain process ownership until pump-driven cleanup finishes."""
        if self._pending.contains(name):
            self._pending.stop(name)
            return
        session = self.get(name)
        self._pending.add(name, session.close())
        del self._sessions[name]
        self._pending.stop(name)

    def close(self) -> None:
        """Attempt every session; keep failed closures tracked for a retry."""
        failures: list[Exception] = []
        for name in list(self._sessions):
            try:
                self.kill(name)
            except (OSError, RuntimeError) as error:
                failures.append(error)
        failures.extend(self._pending.close())
        if failures:
            raise ExceptionGroup("terminal session shutdown failed", failures)
