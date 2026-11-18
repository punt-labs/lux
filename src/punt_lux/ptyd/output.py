"""Ordered output and a captured terminal checkpoint, independent of sockets."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Self

from punt_lux.protocol.pty.control_fields import ControlError, ControlFields


@dataclass(frozen=True, slots=True)
class OutputChunk:
    """Bytes beginning at an authoritative position in one session's output."""

    session: str
    start: int
    data: bytes

    @property
    def end(self) -> int:
        return self.start + len(self.data)


@dataclass(frozen=True, slots=True)
class SessionSnapshot:
    """Owned snapshot bytes and their exact cut through the output stream."""

    session: str
    position: int
    cols: int
    rows: int
    version: str
    data: bytes

    def to_dict(self) -> dict[str, object]:
        """Metadata only; binary snapshot bytes never enter the JSON channel."""
        return {
            "session": self.session,
            "position": self.position,
            "cols": self.cols,
            "rows": self.rows,
            "snapshot_version": self.version,
            "format": "binary",
            "size": len(self.data),
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, object], data: bytes) -> Self:
        """Rejoin validated wire metadata with a completed binary transfer."""
        fields = ControlFields(raw)
        if fields.text("format") != "binary":
            raise ControlError("unsupported snapshot format")
        size = fields.integer("size", 1, 16 * 1024 * 1024)
        if len(data) != size:
            raise ControlError("snapshot transfer length does not match metadata")
        return cls(
            fields.session(),
            fields.integer("position", 0, (1 << 63) - 1),
            fields.integer("cols", 1, 1024),
            fields.integer("rows", 1, 512),
            fields.text("snapshot_version", 128),
            data,
        )
