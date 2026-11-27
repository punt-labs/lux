"""What a reconcile changes: windows to open, windows to close."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Set
from dataclasses import dataclass
from typing import Self

from punt_lux.pty.listed_session import ListedSession
from punt_lux.wire.stream.session_events import SessionEvent


@dataclass(frozen=True, slots=True)
class SyncPlan:
    """The difference between the daemon's running sessions and the windows shown."""

    opened: tuple[ListedSession, ...]
    closed: tuple[str, ...]

    @classmethod
    def reconcile(
        cls,
        listed: Mapping[str, str],
        events: Iterable[SessionEvent],
        shown: Set[str],
    ) -> Self:
        """Bring a listing up to date with the events buffered since it was asked.

        The listing is the authority at the moment it was taken; the events
        carry it forward. An exit wins over a creation of the same id, because
        ids are never reused.
        """
        running = cls._running(listed, tuple(events))
        return cls(
            tuple(
                ListedSession(session, label, "running")
                for session, label in running.items()
                if session not in shown
            ),
            tuple(sorted(shown - running.keys())),
        )

    @staticmethod
    def _running(
        listed: Mapping[str, str], events: tuple[SessionEvent, ...]
    ) -> dict[str, str]:
        ended = {e.session for e in events if e.kind == "ended"}
        born = {e.session: e.label for e in events if e.kind == "created"}
        return {s: n for s, n in {**listed, **born}.items() if s not in ended}
