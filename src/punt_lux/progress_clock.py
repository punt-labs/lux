"""ProgressClock -- when a byte last moved on a socket, so a deadline can be re-armed.

A peer that is slow but alive keeps moving bytes; one that has stopped moves none. A
bound on *elapsed* time cuts the first short, so the bound is on time *without
progress* instead: every byte that moves restarts the window.
"""

from __future__ import annotations

import time
from typing import Self, final

__all__ = ["ProgressClock"]


@final
class ProgressClock:
    """The monotonic time a byte last moved, and the deadline it implies."""

    _last: float
    __slots__ = ("_last",)

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._last = time.monotonic()
        return self

    def moved(self) -> None:
        """Note that a byte moved just now."""
        self._last = time.monotonic()

    def expires_at(self, window: float) -> float:
        """The monotonic time ``window`` seconds after the last progress."""
        return self._last + window

    def progressed_within(self, window: float) -> bool:
        """Whether a byte moved less than ``window`` seconds ago."""
        return time.monotonic() < self._last + window
