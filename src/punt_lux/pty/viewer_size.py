"""The terminal size a viewer asked for, and the size its snapshots have."""

from __future__ import annotations

from typing import Self


class ViewerSize:
    """Track wanted against actual size, in cells."""

    _wanted: tuple[int, int]
    _actual: tuple[int, int]

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._wanted = self._actual = (80, 24)
        return self

    @property
    def wanted(self) -> tuple[int, int]:
        return self._wanted

    @property
    def actual(self) -> tuple[int, int]:
        return self._actual

    def want(self, size: tuple[int, int]) -> None:
        self._wanted = size

    def measured(self, size: tuple[int, int]) -> None:
        self._actual = size
