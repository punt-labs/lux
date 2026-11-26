"""The daemon's ``list`` reply, decoded into the sessions it names."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Self, cast

from punt_lux.pty.daemon_exchange import SessionRefusedError
from punt_lux.pty.listed_session import ListedSession


class SessionListing:
    """Answer which listed sessions run, and which running one holds a label."""

    _running: dict[str, str]

    def __new__(cls, running: dict[str, str]) -> Self:
        self = super().__new__(cls)
        self._running = running
        return self

    @classmethod
    def from_result(cls, result: Mapping[str, object]) -> Self:
        """Decode a ``list`` reply's result.

        Raises:
            SessionRefusedError: The result carries no list of sessions.
        """
        return cls({s.session: s.label for s in cls._rows(result) if s.is_running})

    @staticmethod
    def _rows(result: Mapping[str, object]) -> list[ListedSession]:
        if not isinstance(sessions := result.get("sessions"), list):
            raise SessionRefusedError("luxd-pty answered list without sessions")
        return ListedSession.well_formed(cast("list[object]", sessions))

    def is_running(self, session: str) -> bool:
        """Say whether ``session`` is listed as running."""
        return session in self._running

    def running_under(self, label: str) -> str:
        """Return the running session holding ``label``, or ``""``."""
        return next((s for s, held in self._running.items() if held == label), "")
