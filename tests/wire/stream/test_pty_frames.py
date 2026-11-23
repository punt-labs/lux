"""Fragmentation, coalescing, bounds and EOF for the local PTY transport."""

from __future__ import annotations

import struct
from typing import cast

import pytest

from punt_lux.wire.stream.frames import (
    MAX_PAYLOAD_BYTES,
    MAX_READ_BYTES,
    Frame,
    FrameDecoder,
    FrameError,
    FrameKind,
)


def test_header_layout_and_empty_frame() -> None:
    frame = Frame(7, FrameKind.CLOSE, b"")
    assert frame.encode() == struct.pack("<IBI", 7, 4, 0)
    decoder = FrameDecoder()
    assert decoder.feed(frame.encode()) == [frame]
    assert decoder.pending_bytes == 0
    decoder.finish()


@pytest.mark.parametrize("kind", list(FrameKind))
def test_each_kind_round_trips_arbitrary_bytes(kind: FrameKind) -> None:
    frame = Frame(42, kind, bytes(range(256)))
    assert FrameDecoder().feed(frame.encode()) == [frame]


@pytest.mark.parametrize("split", range(18))
def test_every_split_across_header_and_payload(split: int) -> None:
    frame = Frame(9, FrameKind.DATA, b"abcdefgh")
    wire = frame.encode()
    decoder = FrameDecoder()
    output = decoder.feed(wire[:split]) + decoder.feed(wire[split:])
    assert output == [frame]
    assert decoder.pending_bytes == 0
    decoder.finish()


def test_one_byte_at_a_time() -> None:
    frame = Frame(1, FrameKind.SNAPSHOT, b"fragmented snapshot")
    decoder = FrameDecoder()
    output: list[Frame] = []
    for byte in frame.encode():
        output.extend(decoder.feed(bytes([byte])))
    assert output == [frame]


def test_coalesced_frames_keep_channel_order() -> None:
    frames = [
        Frame(0, FrameKind.DATA, b'{"id":1}'),
        Frame(2, FrameKind.DATA, b"terminal bytes"),
        Frame(4, FrameKind.CREDIT, struct.pack("<I", 1234)),
    ]
    assert FrameDecoder().feed(b"".join(f.encode() for f in frames)) == frames


def test_maximum_payload_arrives_in_bounded_reads() -> None:
    frame = Frame(1, FrameKind.SNAPSHOT, b"s" * MAX_PAYLOAD_BYTES)
    wire = frame.encode()
    decoder = FrameDecoder()
    output: list[Frame] = []
    for offset in range(0, len(wire), MAX_READ_BYTES):
        output.extend(decoder.feed(wire[offset : offset + MAX_READ_BYTES]))
        assert decoder.pending_bytes <= MAX_PAYLOAD_BYTES + Frame.HEADER_BYTES
    assert output == [frame]
    assert decoder.pending_bytes == 0


@pytest.mark.parametrize("channel", [-1, 1 << 32])
def test_channel_must_fit_header(channel: int) -> None:
    with pytest.raises(FrameError, match="channel"):
        Frame(channel, FrameKind.DATA, b"")


@pytest.mark.parametrize("value", [True, 1.5, "7"])
def test_channel_rejects_non_integer_values(value: object) -> None:
    with pytest.raises(FrameError, match="channel"):
        Frame(cast("int", value), FrameKind.DATA, b"")


def test_outgoing_payload_is_bounded() -> None:
    with pytest.raises(FrameError, match="payload"):
        Frame(1, FrameKind.DATA, b"x" * (MAX_PAYLOAD_BYTES + 1))


@pytest.mark.parametrize(
    "header",
    [struct.pack("<IBI", 1, 0, MAX_PAYLOAD_BYTES + 1), struct.pack("<IBI", 1, 255, 0)],
)
def test_bad_header_rejected_without_waiting_for_payload(header: bytes) -> None:
    decoder = FrameDecoder()
    with pytest.raises(FrameError):
        decoder.feed(header)
    assert decoder.pending_bytes == 0
    with pytest.raises(FrameError, match="cannot be reused"):
        decoder.feed(Frame(1, FrameKind.DATA, b"ok").encode())


def test_oversize_socket_read_is_rejected() -> None:
    decoder = FrameDecoder()
    with pytest.raises(FrameError, match="receive limit"):
        decoder.feed(b"x" * (MAX_READ_BYTES + 1))
    assert decoder.pending_bytes == 0


@pytest.mark.parametrize("tail", [b"x", struct.pack("<IBI", 1, 0, 10) + b"abc"])
def test_truncated_eof_poisoning(tail: bytes) -> None:
    decoder = FrameDecoder()
    assert decoder.feed(tail) == []
    with pytest.raises(FrameError, match="ended inside"):
        decoder.finish()
    assert decoder.pending_bytes == 0
    with pytest.raises(FrameError, match="cannot be reused"):
        decoder.feed(b"")
