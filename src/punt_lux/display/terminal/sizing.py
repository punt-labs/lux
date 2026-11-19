"""Separate local fitting from authoritative remote grid changes."""

from __future__ import annotations

from typing import Literal, Self


class ViewSizing:
    _actual: tuple[int, int]
    _wanted: tuple[int, int]
    _remote: bool
    _fixed: bool

    def __new__(cls, size: tuple[int, int], *, fixed: bool = False) -> Self:
        self = super().__new__(cls)
        self._actual = self._wanted = size
        self._remote = False
        self._fixed = fixed
        return self

    @property
    def actual(self) -> tuple[int, int]:
        return self._actual

    @property
    def fixed(self) -> bool:
        return self._fixed

    @fixed.setter
    def fixed(self, value: bool) -> None:
        self._fixed = value

    def adopt(self, size: tuple[int, int]) -> None:
        self._actual = size
        if not self._remote:
            self._wanted = size
        self._remote = True

    def accept(self, size: tuple[int, int]) -> None:
        self._actual = size

    def fit(self, size: tuple[int, int]) -> Literal["none", "local", "remote"]:
        if self._remote:
            if size == self._wanted:
                return "none"
            self._wanted = size
            return "remote"
        if self._fixed or size == self._actual:
            return "none"
        self._actual = size
        return "local"
