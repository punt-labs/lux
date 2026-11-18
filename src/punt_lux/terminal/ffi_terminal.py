# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportPrivateUsage=false
"""Typed owner of pyghostty's untyped terminal IO and finalizer boundary."""

from __future__ import annotations

from collections.abc import Callable
from typing import Self, cast

from punt_lux.terminal.ffi import Terminal


class TerminalIO:
    """Bind IO to one native terminal and guard against use after release."""

    _native: Terminal
    _closed: bool

    def __new__(cls, native: Terminal) -> Self:
        self = super().__new__(cls)
        self._native = native
        self._closed = False
        return self

    @property
    def native(self) -> Terminal:
        self._check_open()
        return self._native

    @property
    def size(self) -> tuple[int, int]:
        self._check_open()
        return cast("tuple[int, int]", self._native.size)

    def on_reply(self, write: Callable[[bytes], None]) -> None:
        self._check_open()
        self._native.on_reply(write)

    def feed(self, data: bytes) -> None:
        self._check_open()
        self._native.feed(data)

    def resize(self, cols: int, rows: int) -> None:
        self._check_open()
        self._native.resize(cols, rows)

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._native._free()

    def _check_open(self) -> None:
        if self._closed:
            raise RuntimeError("native terminal is closed")
