"""Bound how long one viewer may wait for a repaint that cannot be cut."""

from __future__ import annotations

import logging
from typing import Self

logger = logging.getLogger(__name__)

REPAINT_LIMIT = 3


class RepaintFailures:
    """Count consecutive failed repaints of one viewer; warn on first and last."""

    _limit: int
    _count: int

    def __new__(cls, limit: int = REPAINT_LIMIT) -> Self:
        self = super().__new__(cls)
        self._limit = limit
        self._count = 0
        return self

    def record(self, session: str, error: Exception, size: tuple[int, int]) -> bool:
        """Count one failure; return whether the viewer should now be closed."""
        self._count += 1
        exhausted = self._count >= self._limit
        if self._count == 1 or exhausted:
            logger.warning(
                "terminal %s: repaint failed %d/%d at %dx%d: %s",
                session,
                self._count,
                self._limit,
                *size,
                error,
            )
        return exhausted

    def clear(self) -> None:
        self._count = 0
