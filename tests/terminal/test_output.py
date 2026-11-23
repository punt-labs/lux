"""Output offsets and snapshot metadata preserve the terminal transfer contract."""

from __future__ import annotations

import pytest

from punt_lux.terminal.output import OutputChunk, SessionSnapshot
from punt_lux.terminal.snapshot import screen_rows, tracked_terminal
from punt_lux.terminal.snapshot_encoding import SnapshotEncoding
from punt_lux.wire.stream.control_fields import ControlError


@pytest.mark.parametrize("data", [b"", b"abc", b"\xff\x00"])
def test_output_end_is_the_exclusive_byte_offset(data: bytes) -> None:
    chunk = OutputChunk("shell", 7, data)
    assert chunk.session == "shell"
    assert chunk.start == 7
    assert chunk.data == data
    assert chunk.end == 7 + len(data)


@pytest.mark.parametrize("encoding", list(SnapshotEncoding))
def test_snapshot_metadata_round_trips_without_inline_bytes(
    encoding: SnapshotEncoding,
) -> None:
    snapshot = SessionSnapshot("tmux", 7, 20, 4, "v", b"paint", encoding)
    metadata = snapshot.to_dict()
    assert metadata == {
        "session": "tmux",
        "position": 7,
        "cols": 20,
        "rows": 4,
        "snapshot_version": "v",
        "format": encoding.value,
        "size": 5,
    }
    assert SessionSnapshot.from_dict(metadata, snapshot.data) == snapshot
    assert snapshot.is_checkpoint is (encoding is SnapshotEncoding.BINARY)


def test_snapshots_default_to_binary_checkpoints() -> None:
    snapshot = SessionSnapshot("shell", 0, 20, 4, "v", b"paint")
    assert snapshot.encoding is SnapshotEncoding.BINARY
    assert snapshot.is_checkpoint


@pytest.mark.parametrize("data", [b"", b"pa", b"paint too long"])
def test_transfer_length_must_match_metadata(data: bytes) -> None:
    snapshot = SessionSnapshot("shell", 0, 20, 4, "v", b"paint")
    with pytest.raises(ControlError, match="length"):
        SessionSnapshot.from_dict(snapshot.to_dict(), data)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("format", "mystery"),
        ("position", -1),
        ("cols", 0),
        ("rows", 513),
        ("size", 0),
        ("session", "bad/name"),
        ("snapshot_version", "v" * 129),
    ],
)
def test_invalid_snapshot_metadata_is_rejected(field: str, value: object) -> None:
    metadata = SessionSnapshot("shell", 0, 20, 4, "v", b"paint").to_dict()
    metadata[field] = value
    with pytest.raises(ControlError, match=field):
        SessionSnapshot.from_dict(metadata, b"paint")


@pytest.mark.parametrize("encoding", list(SnapshotEncoding))
def test_snapshot_restores_according_to_its_encoding(
    encoding: SnapshotEncoding,
) -> None:
    source = tracked_terminal(20, 4)
    source.feed("hello\r\nworld")
    snapshot = SessionSnapshot(
        "shell", 0, 20, 4, "v", encoding.serialize(source), encoding
    )
    restored = snapshot.restore()
    assert screen_rows(restored) == screen_rows(source)
    assert restored.cursor == source.cursor
