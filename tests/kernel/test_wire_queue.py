"""Bounded queue batches preserve order without consuming queued bytes."""

from __future__ import annotations

import pytest

from punt_lux.kernel.wire_queue import WireQueue


class TestWireQueue:
    @pytest.mark.parametrize(
        ("chunks", "advance"),
        [
            ([b"abc"], 0),
            ([b"abc", b"DEFG", b"hij"], 0),
            ([b"abc", b"DEFG", b"hij"], 5),
            ([b"a" * 65536, b"b"], 0),
            ([b"a" * 32000, b"b" * 40000, b"c"], 7),
        ],
    )
    def test_batch_preserves_the_pending_stream(
        self, chunks: list[bytes], advance: int
    ) -> None:
        expected = b"".join(chunks)[advance:]
        queue = WireQueue(100000)
        for chunk in chunks:
            queue.append(chunk)
        queue.advance(advance)
        assert bytes(queue.batch()) == expected[:65536]
        assert bytes(queue.batch()) == expected[:65536]
        assert queue.pending == len(expected)

    def test_empty_append_and_clear_leave_no_pending_bytes(self) -> None:
        queue = WireQueue(3)
        queue.append(b"")
        assert queue.pending == 0
        queue.append(b"abc")
        queue.clear()
        assert queue.pending == 0
        queue.append(b"xyz")
        assert bytes(queue.batch()) == b"xyz"

    def test_overflow_preserves_the_previous_batch(self) -> None:
        queue = WireQueue(3)
        queue.append(b"abc")
        with pytest.raises(BufferError, match="viewer output queue is full"):
            queue.append(b"d")
        assert queue.pending == 3
        assert bytes(queue.batch()) == b"abc"

    def test_empty_queue_has_no_batch(self) -> None:
        with pytest.raises(IndexError):
            WireQueue(3).batch()
