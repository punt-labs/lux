"""One well-formed row of the daemon's ``list`` reply."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Self, cast

_FIELDS = ("session", "label", "state")


class ListedSession:
    """A session the daemon listed, with the id, label and state it reported."""

    _session: str
    _label: str
    _state: str

    def __new__(cls, session: object, label: object, state: object) -> Self:
        """Hold one listed session.

        Raises:
            ValueError: The id is not a non-empty string, or the label or state
                is not a string.
        """
        if not all(isinstance(v, str) for v in (session, label, state)):
            raise ValueError("listed session, label and state must be strings")
        if not session:
            raise ValueError("listed session session id is empty")
        self = super().__new__(cls)
        self._session = cast("str", session)
        self._label, self._state = cast("str", label), cast("str", state)
        return self

    @classmethod
    def well_formed(cls, rows: list[object]) -> list[Self]:
        """Return the sessions the rows describe, ignoring rows that name none.

        A malformed row must never name a session: construction refuses it.
        """
        return [s for r in rows if (s := cls._from_row(r)) is not None]

    @classmethod
    def _from_row(cls, row: object) -> Self | None:
        if not isinstance(row, Mapping):
            return None
        fields = cast("Mapping[str, object]", row)
        try:
            return cls(*(fields.get(key) for key in _FIELDS))
        except ValueError:
            return None

    @property
    def session(self) -> str:
        """The id the daemon gave the session."""
        return self._session

    @property
    def label(self) -> str:
        """The label the session holds."""
        return self._label

    @property
    def is_running(self) -> bool:
        """Whether the session is listed as running."""
        return self._state == "running"
