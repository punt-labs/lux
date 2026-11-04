"""WriteProgress -- the silence window of one write, which starts when the write does.

A write is cut only after ``window`` with no byte moving on the socket. The line's
clock says when a byte last moved, but on an idle dial that was long ago, and a write
that has only just got the line must not be judged by the idleness before it: its
window starts at the later of the line's last byte and its own start, which is local to
the write. Every byte it moves is progress for whoever waits on the line.
"""

from __future__ import annotations

from typing import Protocol, Self, final

from punt_lux.progress_clock import ProgressClock

__all__ = ["ProgressSource", "WriteProgress"]


class ProgressSource(Protocol):
    """What a bounded send asks of its clock: its deadline, and a byte having moved."""

    def expires_at(self, window: float) -> float:
        """The monotonic time ``window`` seconds after the last progress."""
        ...

    def moved(self) -> None:
        """Note that a byte moved just now."""
        ...


@final
class WriteProgress:
    """One write's window over the line's clock."""

    _line: ProgressClock
    _own: ProgressClock
    __slots__ = ("_line", "_own")

    def __new__(cls, line: ProgressClock) -> Self:
        self = super().__new__(cls)
        self._line = line
        self._own = ProgressClock()  # made when the write starts
        return self

    def expires_at(self, window: float) -> float:
        """``window`` after the later of the line's last byte and this write's start."""
        return max(self._line.expires_at(window), self._own.expires_at(window))

    def moved(self) -> None:
        """Note a byte of this write: progress for the line."""
        self._own.moved()
        self._line.moved()
