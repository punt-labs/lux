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

    def __new__(cls, session: str, label: str, state: str) -> Self:
        self = super().__new__(cls)
        self._session, self._label, self._state = session, label, state
        return self

    @classmethod
    def well_formed(cls, rows: list[object]) -> list[Self]:
        """Return the rows with a non-empty string id and string label and state.

        Other rows are ignored: a malformed row must never name a session.
        """
        return [
            cls(*(cast("str", row[key]) for key in _FIELDS))
            for row in cls._mappings(rows)
            if cls._is_well_formed(row)
        ]

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

    @staticmethod
    def _mappings(rows: list[object]) -> list[Mapping[str, object]]:
        return [cast("Mapping[str, object]", r) for r in rows if isinstance(r, Mapping)]

    @staticmethod
    def _is_well_formed(row: Mapping[str, object]) -> bool:
        return all(isinstance(row.get(key), str) for key in _FIELDS) and bool(
            row["session"]
        )
