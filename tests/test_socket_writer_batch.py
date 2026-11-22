"""Coalesced credit frames preserve order and bounded/partial send semantics."""

from __future__ import annotations

import pytest

from punt_lux.socket_writer import SocketWriter


class CollectingSender:
    def __init__(self, capacity: int = 100_000) -> None:
        self.capacity = capacity
        self.received = bytearray()
        self.calls: list[int] = []

    def send(self, data: memoryview, /) -> int:
        count = min(self.capacity, len(data))
        self.calls.append(len(data))
        self.received.extend(data[:count])
        return count


def test_tiny_acknowledgments_do_not_require_one_pump_each_before_input() -> None:
    writer = SocketWriter()
    sender = CollectingSender()
    for _ in range(200):
        writer.append(b"ack\n")
    writer.append(b"KEY\n")
    writer.flush(sender)
    assert bytes(sender.received) == b"ack\n" * 200 + b"KEY\n"
    assert sender.calls == [804]
    assert writer.pending_bytes == 0


def test_short_send_advances_across_chunk_boundaries() -> None:
    writer = SocketWriter()
    sender = CollectingSender(capacity=7)
    for part in (b"abc", b"DEFG", b"hij"):
        writer.append(part)
    writer.flush(sender)
    assert writer.pending_bytes == 3
    writer.flush(sender)
    assert writer.pending_bytes == 0
    assert bytes(sender.received) == b"abcDEFGhij"
    assert sender.calls == [10, 3]


def test_one_send_batch_never_exceeds_64k() -> None:
    writer = SocketWriter()
    sender = CollectingSender()
    expected = b"a" * 32_000 + b"b" * 40_000 + b"c" * 40_000
    for part in (b"a" * 32_000, b"b" * 40_000, b"c" * 40_000):
        writer.append(part)
    writer.flush(sender)
    assert sender.calls == [64 * 1024]
    assert writer.pending_bytes == len(expected) - 64 * 1024
    writer.flush(sender)
    assert writer.pending_bytes == 0
    assert bytes(sender.received) == expected


def test_zero_send_leaves_queued_bytes_for_owner_cleanup() -> None:
    writer = SocketWriter()
    writer.append(b"data")
    with pytest.raises(ConnectionError):
        writer.flush(CollectingSender(capacity=0))
    assert writer.pending_bytes == 4


def test_varied_partial_batches_preserve_the_exact_byte_stream() -> None:
    for case in range(32):
        chunks = [
            bytes([index]) * (((index + 1) * (case + 7) * 7919) % 4095 + 1)
            for index in range(40)
        ]
        expected = b"".join(chunks)
        writer = SocketWriter()
        sender = CollectingSender(capacity=(case * 747) % 8191 + 1)
        for part in chunks:
            writer.append(part)
        while writer.pending_bytes:
            writer.flush(sender)
        assert bytes(sender.received) == expected
        assert max(sender.calls) <= 64 * 1024
