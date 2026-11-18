"""Socket output remains ordered across short sends and backpressure."""

from __future__ import annotations

import pytest

from punt_lux.ptyd.writer import WireWriter


class FakeSender:
    def __init__(self) -> None:
        self.counts = [2, 0, 3]
        self.attempted: list[bytes] = []

    def send(self, data: memoryview, /) -> int:
        self.attempted.append(bytes(data))
        result = self.counts.pop(0)
        if not result:
            raise BlockingIOError
        return result


def test_short_send_and_eagain_keep_tail() -> None:
    writer = WireWriter()
    sender = FakeSender()
    writer.append(b"hello")
    writer.flush(sender)
    assert writer.pending_bytes == 3
    writer.flush(sender)
    assert writer.pending_bytes == 3
    writer.flush(sender)
    assert writer.pending_bytes == 0
    assert sender.attempted == [b"hello", b"llo", b"llo"]


def test_full_queue_rejects_new_data_without_discarding_old() -> None:
    writer = WireWriter(limit=4)
    writer.append(b"abc")
    with pytest.raises(BufferError):
        writer.append(b"de")
    assert writer.pending_bytes == 3
    writer.clear()
    assert writer.pending_bytes == 0
