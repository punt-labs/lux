"""Per-session retry deadlines with capped exponential backoff."""

from __future__ import annotations

from typing import Self

from punt_lux.display.terminal.remote import RemoteSession


class RetrySchedule:
    _retries: dict[str, tuple[RemoteSession, float]]
    _delays: dict[str, float]

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._retries = {}
        self._delays = {}
        return self

    def failed(self, session: RemoteSession, now: float) -> None:
        delay = min(4.0, self._delays.get(session.name, 0.125) * 2)
        self._delays[session.name] = delay
        self._retries[session.name] = (session, now + delay)

    def due(self, now: float) -> tuple[RemoteSession, ...]:
        due = tuple(
            session for session, deadline in self._retries.values() if now >= deadline
        )
        for session in due:
            del self._retries[session.name]
        return due

    def succeeded(self, session: RemoteSession) -> None:
        self._delays.pop(session.name, None)

    def discard(self, session: RemoteSession) -> None:
        self._retries.pop(session.name, None)
        self._delays.pop(session.name, None)

    def clear(self) -> None:
        self._retries.clear()
        self._delays.clear()
