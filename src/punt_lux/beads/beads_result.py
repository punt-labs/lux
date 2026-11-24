"""What loading beads produced: the issues, or the reason there are none.

A load has two outcomes and they are not the same shape. It either read issues —
possibly zero of them, which is a board saying the backlog is empty — or it could
not read at all, and has a reason to show instead. Carrying both in one tuple
whose second half is sometimes a reason makes every caller re-derive which
happened; these two classes make the caller ask once and dispatch.
"""

from __future__ import annotations

from typing import Any, Self, final

__all__ = ["BeadsFailure", "BeadsResult", "BeadsRows"]


@final
class BeadsRows:
    """A successful load: the issues it read, in the order they should show.

    Empty is a success, not a failure — a repository with nothing open has an
    empty board, and that reads differently from one whose ``bd`` would not run.
    """

    # bd's own JSON objects, untyped at this boundary: the board renders whatever
    # fields the tracker emits, and pinning a schema here would break on its next
    # field. The payload builder is what knows which keys it needs.
    _issues: tuple[dict[str, Any], ...]
    __slots__ = ("_issues",)

    def __new__(cls, issues: tuple[dict[str, Any], ...]) -> Self:
        self = super().__new__(cls)
        self._issues = issues
        return self

    @classmethod
    def of(cls, issues: list[dict[str, Any]]) -> Self:
        """Take a load's issues, freezing the list the caller read them into."""
        return cls(tuple(issues))

    @property
    def issues(self) -> list[dict[str, Any]]:
        """The issues, as the list the payload builder and the sorts work on."""
        return list(self._issues)

    def __len__(self) -> int:
        """How many issues were read, so an empty board is ``not result``."""
        return len(self._issues)


@final
class BeadsFailure:
    """A load that could not read: the reason, worded for the user to see.

    The reason is rendered in the window rather than logged, because the user is
    looking at the board they just asked for and needs to know why it is empty.
    """

    _reason: str
    __slots__ = ("_reason",)

    def __new__(cls, reason: str) -> Self:
        self = super().__new__(cls)
        self._reason = reason
        return self

    @property
    def reason(self) -> str:
        """Why nothing was read — a short phrase, not a traceback."""
        return self._reason


# What every beads load answers with. Callers match on it; nothing unpacks a
# tuple and re-tests which half is set.
type BeadsResult = BeadsRows | BeadsFailure
