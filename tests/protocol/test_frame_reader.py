"""FrameReader.iter_typed: messages one at a time, a bad frame left where it is."""

from __future__ import annotations

import struct

import pytest

from punt_lux.protocol import (
    HEADER_FORMAT,
    FrameReader,
    PingMessage,
    encode_message,
)


def _frame(payload: bytes) -> bytes:
    return struct.pack(HEADER_FORMAT, len(payload)) + payload


class TestIterTyped:
    def test_yields_each_complete_message(self) -> None:
        reader = FrameReader()
        reader.feed(
            encode_message(PingMessage(ts=1.0)) + encode_message(PingMessage(ts=2.0))
        )

        assert list(reader.iter_typed()) == [PingMessage(ts=1.0), PingMessage(ts=2.0)]

    def test_a_partial_frame_waits_for_the_rest(self) -> None:
        reader = FrameReader()
        wire = encode_message(PingMessage(ts=3.0))
        reader.feed(wire[:5])

        assert list(reader.iter_typed()) == []
        reader.feed(wire[5:])
        assert list(reader.iter_typed()) == [PingMessage(ts=3.0)]

    def test_messages_before_a_bad_frame_come_out_before_it_raises(self) -> None:
        reader = FrameReader()
        reader.feed(encode_message(PingMessage(ts=1.0)) + _frame(b"{not json"))
        messages = reader.iter_typed()

        assert next(messages) == PingMessage(ts=1.0)
        with pytest.raises(ValueError, match="Expecting"):
            next(messages)

    def test_the_bad_frame_stays_at_the_head_of_the_buffer(self) -> None:
        reader = FrameReader()
        bad = _frame(b"[1]")
        reader.feed(bad)

        with pytest.raises(ValueError, match="Expected JSON object"):
            list(reader.iter_typed())

        assert reader.head(len(bad)) == bad

    def test_an_oversized_length_is_refused(self) -> None:
        reader = FrameReader()
        reader.feed(struct.pack(HEADER_FORMAT, 2**31))

        with pytest.raises(ValueError, match="exceeds maximum"):
            list(reader.iter_typed())
