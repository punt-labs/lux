"""The daemon's ``list`` reply, decoded into the sessions it names."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Self, cast

from punt_lux.pty.daemon_exchange import SessionRefusedError


class SessionListing:
    """Answer which listed sessions run, and which running one holds a label."""

    _running: dict[str, str]

    def __new__(cls, result: Mapping[str, object]) -> Self:
        """Decode a ``list`` reply's result.

        Raises:
            SessionRefusedError: The result carries no list of sessions.
        """
        sessions = result.get("sessions")
        if not isinstance(sessions, list):
            raise SessionRefusedError("luxd-pty answered list without sessions")
        listed = cast("list[object]", sessions)
        self = super().__new__(cls)
        self._running = cls._running_labels(cls._mappings(listed))
        return self

    @staticmethod
    def _mappings(sessions: list[object]) -> list[Mapping[str, object]]:
        return [
            cast("Mapping[str, object]", entry)
            for entry in sessions
            if isinstance(entry, Mapping)
        ]

    @staticmethod
    def _running_labels(entries: list[Mapping[str, object]]) -> dict[str, str]:
        return {
            str(entry.get("session")): str(entry.get("label"))
            for entry in entries
            if entry.get("state") == "running"
        }

    def is_running(self, session: str) -> bool:
        """Say whether ``session`` is listed as running."""
        return session in self._running

    def running_under(self, label: str) -> str:
        """Return the running session holding ``label``, or ``""``."""
        return next((s for s, held in self._running.items() if held == label), "")
