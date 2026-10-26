"""LockDisciplineError -- a lock was taken, or a handler fired, out of order."""

from __future__ import annotations

from punt_lux.domain.programmer_error import ProgrammerError

__all__ = ["LockDisciplineError"]


class LockDisciplineError(ProgrammerError):
    """A lock was taken, released or relied on outside the order the Hub keeps.

    A programmer error: it passes through every fan-out on the interaction path.
    """
