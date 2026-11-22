"""Bounded, replaceable snapshot assembly without any GUI dependency."""

from __future__ import annotations

from typing import Self

from punt_lux.protocol.pty.control_fields import ControlFields
from punt_lux.terminal.ffi import Terminal
from punt_lux.terminal.output import SessionSnapshot
from punt_lux.terminal.snapshot import snapshot_version


class SnapshotTransfer:
    _name: str
    _metadata: dict[str, object]
    _data: bytearray
    _size: int
    _channel: int

    def __new__(cls, name: str) -> Self:
        self = super().__new__(cls)
        self._name = name
        self._metadata = {}
        self._data = bytearray()
        self._size = self._channel = 0
        return self

    @property
    def channel(self) -> int:
        return self._channel

    @property
    def ended(self) -> bool:
        return self._metadata.get("ended") is True

    def begin(self, metadata: dict[str, object]) -> None:
        fields = ControlFields(metadata)
        if (
            fields.session() != self._name
            or fields.text("snapshot_version") != snapshot_version()
        ):
            raise ValueError("snapshot identity/version mismatch")
        self._channel = fields.integer("channel", 1, (1 << 32) - 1)
        self._size = fields.integer("size", 1, 16 * 1024 * 1024)
        self._metadata = metadata
        self._data.clear()

    def feed(self, data: bytes) -> Terminal | None:
        if len(self._data) + len(data) > self._size:
            raise ValueError("oversized snapshot fragment")
        self._data.extend(data)
        if len(self._data) < self._size:
            return None
        checkpoint = SessionSnapshot.from_dict(self._metadata, bytes(self._data))
        native = checkpoint.restore()
        self._data.clear()
        return native

    def clear(self) -> None:
        self._data.clear()
