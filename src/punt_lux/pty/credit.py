"""Per-viewer byte credit; delayed acknowledgments never create extra capacity."""

from __future__ import annotations

from typing import Self


class CreditWindow:
    _available: int
    _inflight: int

    def __new__(cls, capacity: int = 256 * 1024) -> Self:
        if capacity < 1:
            raise ValueError("credit capacity must be positive")
        self = super().__new__(cls)
        self._available = capacity
        self._inflight = 0
        return self

    @property
    def available(self) -> int:
        return self._available

    @property
    def inflight(self) -> int:
        return self._inflight

    def send(self, amount: int) -> None:
        if not 0 < amount <= self._available:
            raise ValueError("send exceeds available viewer credit")
        self._available -= amount
        self._inflight += amount

    def acknowledge(self, amount: int) -> None:
        if not 0 < amount <= self._inflight:
            raise ValueError("credit exceeds bytes actually in flight")
        self._available += amount
        self._inflight -= amount
