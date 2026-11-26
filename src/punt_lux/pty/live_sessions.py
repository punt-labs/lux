"""The sessions a daemon holds, with the ids and labels that name them."""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING, Self

from punt_lux.pty.session_ids import SessionIds
from punt_lux.pty.session_labels import SessionLabels
from punt_lux.pty.session_spec import SessionSpec

if TYPE_CHECKING:
    from punt_lux.pty.session import TerminalSession
    from punt_lux.wire.stream.new_request import NewRequest


class LiveSessions:
    """Own the session map, the id sequence and which label names which session."""

    _sessions: dict[str, TerminalSession]
    _ids: SessionIds
    _labels: SessionLabels

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._sessions = {}
        self._ids = SessionIds.fresh()
        self._labels = SessionLabels()
        return self

    def __len__(self) -> int:
        return len(self._sessions)

    def __iter__(self) -> Iterator[TerminalSession]:
        return iter(tuple(self._sessions.values()))

    def __contains__(self, name: object) -> bool:
        return name in self._sessions

    def finished(self) -> tuple[TerminalSession, ...]:
        """Return the held sessions whose program ended or whose IO failed."""
        return tuple(s for s in self._sessions.values() if s.finished)

    def running_session(self, name: str) -> TerminalSession | None:
        """Return ``name`` while it runs; ``None`` is the answer for any other state."""
        session = self._sessions.get(name)
        return session if session is not None and session.running else None

    def spec(self, request: NewRequest) -> SessionSpec:
        """Name a session about to start: a fresh id and a label no live one holds."""
        return SessionSpec(
            self._ids.next(), self._labels.unique(request.label), request
        )

    def add(self, session: TerminalSession) -> None:
        """Hold ``session`` and reserve its label."""
        self._labels.claim(session)
        self._sessions[session.name] = session

    def get(self, name: str) -> TerminalSession:
        """Return the held session ``name``; ``KeyError`` when none is held."""
        return self._sessions[name]

    def running(self, name: str) -> TerminalSession:
        """Return ``name`` while it runs; a finished or unknown id is refused."""
        session = self._sessions.get(name)
        if session is None or session.finished:
            raise ValueError(f"unknown session {name}")
        return session

    def remove(self, name: str) -> None:
        """Stop holding ``name`` and free its label."""
        del self._sessions[name]
        self._labels.release(name)
