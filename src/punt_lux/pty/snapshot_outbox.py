"""A snapshot being sent to a viewer in credit-sized pieces."""

from __future__ import annotations

from typing import Self


class SnapshotOutbox:
    """A snapshot being sent in credit-sized pieces."""

    _data: bytes
    _offset: int

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._data = b""
        self._offset = 0
        return self

    def __len__(self) -> int:
        return len(self._data) - self._offset

    def load(self, data: bytes) -> None:
        """Replace whatever is unsent with ``data``."""
        self._data, self._offset = data, 0

    def take(self, count: int) -> bytes:
        """Remove and return up to ``count`` unsent bytes."""
        data = self._data[self._offset : self._offset + count]
        self._offset += len(data)
        if not self:
            self.load(b"")
        return data
