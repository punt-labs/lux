"""Snapshot encoding selects the wire format and its matching restore policy."""

from __future__ import annotations

import pytest

from punt_lux.protocol.pty.control_fields import ControlError
from punt_lux.terminal.snapshot import SnapshotError, screen_rows, tracked_terminal
from punt_lux.terminal.snapshot_encoding import SnapshotEncoding


@pytest.mark.parametrize("encoding", list(SnapshotEncoding))
def test_parse_accepts_wire_format_names(encoding: SnapshotEncoding) -> None:
    assert SnapshotEncoding.parse(encoding.value) is encoding


@pytest.mark.parametrize("text", ["", "BINARY", "mystery"])
def test_parse_rejects_unknown_formats(text: str) -> None:
    with pytest.raises(ControlError, match="unsupported snapshot format"):
        SnapshotEncoding.parse(text)


@pytest.mark.parametrize("encoding", list(SnapshotEncoding))
@pytest.mark.parametrize("text", ["", "hello\r\nworld"])
def test_encoding_round_trips_visible_state(
    encoding: SnapshotEncoding, text: str
) -> None:
    source = tracked_terminal(20, 4)
    source.feed(text)
    restored = encoding.restore(encoding.serialize(source), 20, 4)
    assert screen_rows(restored) == screen_rows(source)
    assert restored.cursor == source.cursor


@pytest.mark.parametrize("data", [b"", b"not a terminal snapshot"])
def test_binary_restore_rejects_invalid_snapshot_bytes(data: bytes) -> None:
    with pytest.raises(SnapshotError):
        SnapshotEncoding.BINARY.restore(data, 20, 4)


def test_empty_visible_repaint_restores_a_blank_terminal() -> None:
    restored = SnapshotEncoding.VT.restore(b"", 7, 2)
    assert screen_rows(restored) == ["", ""]
    assert restored.cursor == (0, 0)
