"""The uninterrupted interval witnessed on a single Hub-to-Display dial."""

from __future__ import annotations

from typing import Self


class DisplayStability:
    """Pending probes and replacement dials cannot inherit an earlier interval."""

    __slots__ = ("_seconds", "_witness")
    _seconds: float
    _witness: tuple[str, float] | None

    def __new__(cls, seconds: float) -> Self:
        self = super().__new__(cls)
        self._seconds = seconds
        self._witness = None
        return self

    @property
    def started(self) -> bool:
        return self._witness is not None

    def observe(self, identity: str | None, now: float) -> bool:
        """Credit only observations since this dial's first consecutive reply."""
        if not identity:
            self._witness = None
            return False
        if self._witness is None or self._witness[0] != identity:
            self._witness = (identity, now)
        return now - self._witness[1] >= self._seconds

    def phase(self, now: float) -> str:
        if self._witness is None:
            return "before connecting to Hub"
        return f"after {now - self._witness[1]:.1f}s connected to Hub"
