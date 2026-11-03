"""FrameReader.iter_typed: messages one at a time, a bad frame left where it is."""

from __future__ import annotations

import struct
from typing import Any

import pytest

from punt_lux.protocol import (
    HEADER_FORMAT,
    FrameReader,
    Message,
    PingMessage,
    PongMessage,
    SceneMessage,
    encode_message,
    message_from_dict,
)
from punt_lux.protocol.messages.wire_vocabulary import (
    CLIENT_VOCABULARY,
    DISPLAY_VOCABULARY,
)


def _frame(payload: bytes) -> bytes:
    return struct.pack(HEADER_FORMAT, len(payload)) + payload


class TestIterTyped:
    def test_yields_each_complete_message(self) -> None:
        reader = FrameReader()
        reader.feed(
            encode_message(PongMessage(ts=1.0)) + encode_message(PongMessage(ts=2.0))
        )

        assert list(reader.iter_typed(DISPLAY_VOCABULARY)) == [
            PongMessage(ts=1.0),
            PongMessage(ts=2.0),
        ]

    def test_a_partial_frame_waits_for_the_rest(self) -> None:
        reader = FrameReader()
        wire = encode_message(PongMessage(ts=3.0))
        reader.feed(wire[:5])

        assert list(reader.iter_typed(DISPLAY_VOCABULARY)) == []
        reader.feed(wire[5:])
        assert list(reader.iter_typed(DISPLAY_VOCABULARY)) == [PongMessage(ts=3.0)]

    def test_messages_before_a_bad_frame_come_out_before_it_raises(self) -> None:
        reader = FrameReader()
        reader.feed(encode_message(PongMessage(ts=1.0)) + _frame(b"{not json"))
        messages = reader.iter_typed(DISPLAY_VOCABULARY)

        assert next(messages) == PongMessage(ts=1.0)
        with pytest.raises(ValueError, match="Expecting"):
            next(messages)

    def test_the_bad_frame_stays_at_the_head_of_the_buffer(self) -> None:
        reader = FrameReader()
        bad = _frame(b"[1]")
        reader.feed(bad)

        with pytest.raises(ValueError, match="Expected JSON object"):
            list(reader.iter_typed(DISPLAY_VOCABULARY))

        assert reader.head(len(bad)) == bad

    def test_an_oversized_length_is_refused(self) -> None:
        reader = FrameReader()
        reader.feed(struct.pack(HEADER_FORMAT, 2**31))

        with pytest.raises(ValueError, match="exceeds maximum"):
            list(reader.iter_typed(DISPLAY_VOCABULARY))


def _scene() -> bytes:
    return encode_message(SceneMessage(id="s", elements=[], frame_id="f"))


class TestAcceptedVocabulary:
    def test_a_type_outside_the_vocabulary_is_refused_before_it_is_decoded(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        decoded: list[object] = []

        def spy(raw: dict[str, Any]) -> None:
            decoded.append(raw)

        monkeypatch.setattr("punt_lux.protocol.message_from_dict", spy)
        reader = FrameReader()
        reader.feed(_scene())

        with pytest.raises(ValueError, match="scene"):
            list(reader.iter_typed(DISPLAY_VOCABULARY))

        assert decoded == []

    def test_a_refused_frame_stays_at_the_head_of_the_buffer(self) -> None:
        reader = FrameReader()
        wire = _scene()
        reader.feed(wire)

        with pytest.raises(ValueError, match="not accepted"):
            list(reader.iter_typed(DISPLAY_VOCABULARY))

        assert reader.head(len(wire)) == wire

    def test_a_non_string_type_is_refused_too(self) -> None:
        reader = FrameReader()
        reader.feed(_frame(b'{"type": ["scene"]}'))

        with pytest.raises(ValueError, match="not accepted"):
            list(reader.iter_typed(DISPLAY_VOCABULARY))

    def test_the_vocabulary_is_the_display_message_union(self) -> None:
        assert DISPLAY_VOCABULARY.tags == {
            "ready",
            "ack",
            "remote_invocation",
            "observer",
            "pong",
            "introspect_response",
            "list_scenes_response",
            "screenshot_response",
            "query_response",
        }


class TestDrainTypedSkipsUnknownKinds:
    def test_an_unknown_kind_is_skipped_undecoded_and_the_rest_decoded(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        decoded: list[str] = []
        real = message_from_dict

        def spy(raw: dict[str, Any]) -> Message:
            decoded.append(raw["type"])
            return real(raw)

        monkeypatch.setattr("punt_lux.protocol.message_from_dict", spy)
        reader = FrameReader()
        reader.feed(
            encode_message(PingMessage(ts=1.0))
            + _frame(b'{"type": "from_the_future"}')
            + encode_message(PingMessage(ts=2.0))
        )

        with caplog.at_level("WARNING"):
            messages = reader.drain_typed(CLIENT_VOCABULARY)

        assert messages == [PingMessage(ts=1.0), PingMessage(ts=2.0)]
        assert decoded == ["ping", "ping"]
        assert "from_the_future" in caplog.text
