"""How long a finished session may wait on viewers that never take its output."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Self

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

GRACE_SECONDS = 30.0


class FinishDeadlines:
    """Remember when each finished session was first seen, and who is overdue."""

    _clock: Callable[[], float]
    _grace: float
    _seen: dict[str, float]

    def __new__(
        cls,
        clock: Callable[[], float] = time.monotonic,
        grace: float = GRACE_SECONDS,
    ) -> Self:
        self = super().__new__(cls)
        self._clock, self._grace = clock, grace
        self._seen = {}
        return self

    def overdue(self, name: str) -> bool:
        """Start ``name``'s clock on first sight; say whether the grace is spent."""
        now = self._clock()
        return now - self._seen.setdefault(name, now) >= self._grace

    def keep_only(self, names: Iterable[str]) -> None:
        """Forget every session not in ``names``; it has been removed."""
        held = set(names)
        self._seen = {n: t for n, t in self._seen.items() if n in held}
