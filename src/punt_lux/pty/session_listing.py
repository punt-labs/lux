"""The daemon's ``list`` reply, decoded into the sessions it names."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Self, cast

from punt_lux.pty.daemon_exchange import SessionRefusedError


class SessionListing:
    """Answer questions about the sessions a ``list`` reply holds."""

    _entries: tuple[Mapping[str, object], ...]

    def __new__(cls, result: Mapping[str, object]) -> Self:
        """Decode a ``list`` reply's result.

        Raises:
            SessionRefusedError: The result carries no list of sessions.
        """
        sessions = result.get("sessions")
        if not isinstance(sessions, list):
            raise SessionRefusedError("luxd-pty answered list without sessions")
        self = super().__new__(cls)
        self._entries = tuple(
            cast("Mapping[str, object]", entry)
            for entry in cast("list[object]", sessions)
            if isinstance(entry, Mapping)
        )
        return self

    def is_running(self, session: str) -> bool:
        """Say whether ``session`` is listed as running."""
        return any(
            entry.get("session") == session and entry.get("state") == "running"
            for entry in self._entries
        )

    def running_under(self, label: str) -> str:
        """Return the running session holding ``label``, or ``""``."""
        return self._held_under(label, running=True)

    def stale_under(self, label: str) -> str:
        """Return a session holding ``label`` that is not running, or ``""``."""
        return self._held_under(label, running=False)

    def _held_under(self, label: str, *, running: bool) -> str:
        for entry in self._entries:
            session = entry.get("session")
            if (
                entry.get("label") == label
                and isinstance(session, str)
                and (entry.get("state") == "running") == running
            ):
                return session
        return ""
