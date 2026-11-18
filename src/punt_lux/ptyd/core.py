"""Daemon-owned named sessions, independent of viewer and socket lifetimes."""

from __future__ import annotations

import shlex
from collections.abc import Callable
from typing import Self

from punt_lux.protocol.pty.attach import AttachRequest
from punt_lux.ptyd.holder import PtyHolder
from punt_lux.ptyd.output import OutputChunk
from punt_lux.ptyd.process_port import ProcessPort
from punt_lux.ptyd.session import TerminalSession


class SessionError(RuntimeError):
    """A named-session operation could not be completed."""


class ProcessFactory:
    """Spawn exactly an argv vector, never implicitly run it through a shell."""

    @staticmethod
    def start(request: AttachRequest) -> ProcessPort:
        return PtyHolder(
            shlex.split(request.command), cols=request.cols, rows=request.rows
        )


class SessionCore:
    """One authoritative map, with explicit session removal and bounded count."""

    _sessions: dict[str, TerminalSession]
    _pending: dict[str, ProcessPort]
    _factory: Callable[[AttachRequest], ProcessPort]
    _limit: int

    def __new__(
        cls,
        factory: Callable[[AttachRequest], ProcessPort] = ProcessFactory.start,
        *,
        limit: int = 16,
    ) -> Self:
        if limit < 1:
            raise ValueError("session limit must be positive")
        self = super().__new__(cls)
        self._sessions = {}
        self._pending = {}
        self._factory = factory
        self._limit = limit
        return self

    def acquire(self, request: AttachRequest) -> TerminalSession:
        """Start once; reattach never respawns an exited or running program."""
        if request.session in self._pending:
            raise SessionError("session is waiting for failed-start cleanup")
        existing = self._sessions.get(request.session)
        if existing is not None:
            if request.command and request.command != existing.command:
                raise SessionError("session already exists with another command")
            return existing
        if len(self._sessions) + len(self._pending) >= self._limit:
            raise SessionError("terminal session limit reached")
        process = self._factory(request)
        self._pending[request.session] = process
        try:
            session = TerminalSession(request, process)
        except BaseException as error:
            try:
                self.kill(request.session)
            except (OSError, RuntimeError) as cleanup:
                raise BaseExceptionGroup(
                    "session creation and cleanup failed", [error, cleanup]
                ) from error
            raise
        del self._pending[request.session]
        self._sessions[request.session] = session
        return session

    def get(self, name: str) -> TerminalSession:
        try:
            return self._sessions[name]
        except KeyError as error:
            raise SessionError(f"unknown terminal session {name}") from error

    def pump(self) -> list[OutputChunk]:
        """Read every session regardless of which viewers are attached."""
        output: list[OutputChunk] = []
        for session in self._sessions.values():
            chunk = session.pump()
            if chunk.data:
                output.append(chunk)
        return output

    def resize(self, name: str, cols: int, rows: int) -> None:
        # Apply the same public boundary as initial attachment, including bool
        # rejection and bounds, before touching any native state.
        AttachRequest(1, name, cols=cols, rows=rows)
        self.get(name).resize(cols, rows)

    def describe(self) -> list[dict[str, object]]:
        return [session.describe() for session in self._sessions.values()] + [
            {"session": name, "pid": process.pid, "cleanup_pending": True}
            for name, process in self._pending.items()
        ]

    def kill(self, name: str) -> None:
        """Forget a session only after its process has successfully closed."""
        if name in self._pending:
            self._pending[name].close()
            del self._pending[name]
            return
        session = self.get(name)
        session.close()
        del self._sessions[name]

    def close(self) -> None:
        """Attempt every session; keep failed closures tracked for a retry."""
        failures: list[Exception] = []
        for name in [*self._sessions, *self._pending]:
            try:
                self.kill(name)
            except (OSError, RuntimeError) as error:
                failures.append(error)
        if failures:
            raise ExceptionGroup("terminal session shutdown failed", failures)
