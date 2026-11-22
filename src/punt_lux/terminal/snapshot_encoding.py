"""How a snapshot's bytes become a terminal on the replica."""

from __future__ import annotations

from enum import StrEnum
from typing import Self

from punt_lux.protocol.pty.control_fields import ControlError
from punt_lux.terminal.ffi import Terminal
from punt_lux.terminal.snapshot import (
    VtSnapshot,
    encode_binary,
    restore_binary,
    tracked_terminal,
)


class SnapshotEncoding(StrEnum):
    """BINARY is a serialized terminal; VT is a visible-screen repaint."""

    BINARY = "binary"
    VT = "vt"

    @classmethod
    def parse(cls, text: str) -> Self:
        """Validate a wire ``format`` value."""
        try:
            return cls(text)
        except ValueError:
            raise ControlError("unsupported snapshot format") from None

    def serialize(self, term: Terminal) -> bytes:
        """Serialize ``term``; VT works in any parser state, BINARY does not."""
        if self is SnapshotEncoding.BINARY:
            return encode_binary(term)
        return VtSnapshot(term).encode_visible()

    def restore(self, data: bytes, cols: int, rows: int) -> Terminal:
        """Build a fresh terminal from snapshot bytes of this encoding."""
        if self is SnapshotEncoding.BINARY:
            return restore_binary(data)
        term = tracked_terminal(cols, rows)
        term.feed(data)
        return term
