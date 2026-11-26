"""Labels of live sessions: unique per daemon, freed when the session goes."""

from __future__ import annotations

from typing import Protocol, Self


class Labelled(Protocol):
    """Something that holds a label on behalf of a session id."""

    @property
    def name(self) -> str: ...

    @property
    def label(self) -> str: ...


class SessionLabels:
    """Own which label names which live session."""

    _live: dict[str, str]

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._live = {}
        return self

    def unique(self, requested: str) -> str:
        """Return the label a new session will carry.

        An empty request picks ``Terminal N`` with the lowest N no live
        session holds. A
        requested label that a live session already holds is refused.
        """
        if not requested:
            return self._next_default()
        if requested in self._live:
            raise ValueError(f"label {requested!r} is already in use")
        return requested

    def claim(self, holder: Labelled) -> None:
        """Record that ``holder`` holds its label."""
        if holder.label in self._live:
            raise ValueError(f"label {holder.label!r} is already in use")
        self._live[holder.label] = holder.name

    def release(self, session: str) -> None:
        """Free the label ``session`` holds, if any."""
        self._live = {
            label: owner for label, owner in self._live.items() if owner != session
        }

    def _next_default(self) -> str:
        number = 1
        while f"Terminal {number}" in self._live:
            number += 1
        return f"Terminal {number}"
