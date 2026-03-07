"""Tests for punt_lux.protocol — message types, serialization, framing."""

from __future__ import annotations

import pytest

from punt_lux.protocol import (
    AckMessage,
    ButtonElement,
    ClearMessage,
    FrameReader,
    ImageElement,
    InteractionMessage,
    Message,
    Patch,
    PingMessage,
    PongMessage,
    ReadyMessage,
    SceneMessage,
    SeparatorElement,
    TextElement,
    UpdateMessage,
    WindowMessage,
    decode_frame,
    encode_frame,
    encode_message,
    message_from_dict,
    message_to_dict,
)

# ---------------------------------------------------------------------------
# Element construction
# ---------------------------------------------------------------------------


class TestElements:
    def test_text_element(self):
        e = TextElement(id="t1", content="hello")
        assert e.kind == "text"
        assert e.content == "hello"
        assert e.style is None

    def test_button_element(self):
        e = ButtonElement(id="b1", label="Click", action="submit")
        assert e.kind == "button"
        assert not e.disabled

    def test_image_element_with_path(self):
        e = ImageElement(id="i1", path="/tmp/img.png")
        assert e.path == "/tmp/img.png"
        assert e.data is None

    def test_image_element_with_data(self):
        e = ImageElement(id="i2", data="base64data")
        assert e.data == "base64data"
        assert e.path is None

    def test_image_element_requires_path_or_data(self):
        with pytest.raises(ValueError, match="requires either"):
            ImageElement(id="i3")

    def test_separator_element(self):
        e = SeparatorElement()
        assert e.kind == "separator"
        assert e.id is None

    def test_separator_with_id(self):
        e = SeparatorElement(id="sep1")
        assert e.id == "sep1"


# ---------------------------------------------------------------------------
# Message construction
# ---------------------------------------------------------------------------


class TestMessages:
    def test_scene_message(self):
        msg = SceneMessage(
            id="s1",
            elements=[TextElement(id="t1", content="hi")],
            layout="rows",
            title="Test",
        )
        assert msg.type == "scene"
        assert len(msg.elements) == 1

    def test_update_message(self):
        msg = UpdateMessage(
            scene_id="s1",
            patches=[Patch(id="t1", set={"content": "updated"})],
        )
        assert msg.type == "update"

    def test_clear_message(self):
        msg = ClearMessage()
        assert msg.type == "clear"

    def test_ping_message(self):
        msg = PingMessage(ts=1234.5)
        assert msg.ts == 1234.5

    def test_ready_message(self):
        msg = ReadyMessage()
        assert msg.version == "0.1"
        assert msg.capabilities == []

    def test_ack_message(self):
        msg = AckMessage(scene_id="s1", error="bad scene")
        assert msg.error == "bad scene"

    def test_interaction_message(self):
        msg = InteractionMessage(element_id="b1", action="click", value=42)
        assert msg.value == 42

    def test_window_message(self):
        msg = WindowMessage(event="resized", width=800, height=600)
        assert msg.event == "resized"

    def test_pong_message(self):
        msg = PongMessage(ts=1.0, display_ts=2.0)
        assert msg.display_ts == 2.0


# ---------------------------------------------------------------------------
# Serialization roundtrips
# ---------------------------------------------------------------------------


class TestSerialization:
    def test_scene_roundtrip(self):
        original = SceneMessage(
            id="s1",
            elements=[
                TextElement(id="t1", content="hello", style="heading"),
                ButtonElement(id="b1", label="OK", action="confirm"),
                SeparatorElement(),
                ImageElement(id="i1", path="/tmp/x.png", width=100),
            ],
            layout="rows",
            title="Test Scene",
        )
        d = message_to_dict(original)
        restored = message_from_dict(d)
        assert isinstance(restored, SceneMessage)
        assert restored.id == "s1"
        assert len(restored.elements) == 4
        assert isinstance(restored.elements[0], TextElement)
        assert isinstance(restored.elements[1], ButtonElement)
        assert isinstance(restored.elements[2], SeparatorElement)
        assert isinstance(restored.elements[3], ImageElement)

    def test_update_roundtrip(self):
        original = UpdateMessage(
            scene_id="s1",
            patches=[
                Patch(id="t1", set={"content": "new"}),
                Patch(id="old", remove=True),
            ],
        )
        d = message_to_dict(original)
        restored = message_from_dict(d)
        assert isinstance(restored, UpdateMessage)
        assert len(restored.patches) == 2
        assert restored.patches[1].remove is True

    def test_all_message_types_roundtrip(self):
        messages: list[Message] = [
            ClearMessage(),
            PingMessage(ts=1.0),
            ReadyMessage(capabilities=["implot"]),
            AckMessage(scene_id="s1", ts=2.0),
            InteractionMessage(element_id="b1", action="click"),
            WindowMessage(event="closed"),
            PongMessage(ts=1.0, display_ts=2.0),
        ]
        for msg in messages:
            d = message_to_dict(msg)
            restored = message_from_dict(d)
            assert type(restored) is type(msg)

    def test_unknown_message_type_raises(self):
        with pytest.raises(ValueError, match="Unknown message type"):
            message_from_dict({"type": "bogus"})

    def test_unknown_element_kind_raises(self):
        with pytest.raises(ValueError, match="Unknown element kind"):
            message_from_dict(
                {
                    "type": "scene",
                    "id": "s1",
                    "elements": [{"kind": "bogus", "id": "x"}],
                }
            )

    def test_strip_none_fields(self):
        msg = SceneMessage(id="s1", elements=[], title=None)
        d = message_to_dict(msg)
        assert "title" not in d

    def test_button_disabled_included(self):
        e = ButtonElement(id="b1", label="X", disabled=True)
        scene = SceneMessage(id="s1", elements=[e])
        d = message_to_dict(scene)
        assert d["elements"][0]["disabled"] is True

    def test_button_disabled_false_excluded(self):
        e = ButtonElement(id="b1", label="X", disabled=False)
        scene = SceneMessage(id="s1", elements=[e])
        d = message_to_dict(scene)
        assert "disabled" not in d["elements"][0]


# ---------------------------------------------------------------------------
# Wire framing
# ---------------------------------------------------------------------------


class TestFraming:
    def test_encode_decode_roundtrip(self):
        payload = {"type": "ping", "ts": 1.0}
        frame = encode_frame(payload)
        decoded, remaining = decode_frame(frame)
        assert decoded == payload
        assert remaining == b""

    def test_encode_message_roundtrip(self):
        msg = PingMessage(ts=1.0)
        frame = encode_message(msg)
        decoded, _ = decode_frame(frame)
        restored = message_from_dict(decoded)
        assert isinstance(restored, PingMessage)
        assert restored.ts == 1.0

    def test_incomplete_header(self):
        with pytest.raises(ValueError, match="Incomplete frame header"):
            decode_frame(b"\x00\x00")

    def test_incomplete_payload(self):
        import struct

        frame = struct.pack("!I", 100) + b"x" * 10
        with pytest.raises(ValueError, match="Incomplete frame payload"):
            decode_frame(frame)

    def test_oversized_message_encode(self):
        huge = {"data": "x" * (16 * 1024 * 1024 + 1)}
        with pytest.raises(ValueError, match="exceeds maximum size"):
            encode_frame(huge)

    def test_oversized_message_decode(self):
        import struct

        frame = struct.pack("!I", 16 * 1024 * 1024 + 1) + b"x" * 10
        with pytest.raises(ValueError, match="exceeds maximum size"):
            decode_frame(frame)

    def test_multiple_frames_in_buffer(self):
        f1 = encode_frame({"type": "ping"})
        f2 = encode_frame({"type": "clear"})
        decoded1, rest = decode_frame(f1 + f2)
        decoded2, rest = decode_frame(rest)
        assert decoded1["type"] == "ping"
        assert decoded2["type"] == "clear"
        assert rest == b""


# ---------------------------------------------------------------------------
# FrameReader
# ---------------------------------------------------------------------------


class TestFrameReader:
    def test_single_complete_message(self):
        reader = FrameReader()
        frame = encode_frame({"type": "ping"})
        reader.feed(frame)
        messages = reader.drain()
        assert len(messages) == 1
        assert messages[0]["type"] == "ping"

    def test_partial_feed(self):
        reader = FrameReader()
        frame = encode_frame({"type": "clear"})
        # Feed header only
        reader.feed(frame[:4])
        assert reader.drain() == []
        # Feed rest
        reader.feed(frame[4:])
        messages = reader.drain()
        assert len(messages) == 1

    def test_multiple_messages_in_one_feed(self):
        reader = FrameReader()
        f1 = encode_frame({"type": "ping"})
        f2 = encode_frame({"type": "clear"})
        reader.feed(f1 + f2)
        messages = reader.drain()
        assert len(messages) == 2

    def test_byte_at_a_time(self):
        reader = FrameReader()
        frame = encode_frame({"type": "pong", "ts": 1.0})
        for byte in frame:
            reader.feed(bytes([byte]))
        messages = reader.drain()
        assert len(messages) == 1
        assert messages[0]["type"] == "pong"

    def test_drain_typed(self):
        reader = FrameReader()
        reader.feed(encode_frame({"type": "ping", "ts": 42.0}))
        messages = reader.drain_typed()
        assert len(messages) == 1
        assert isinstance(messages[0], PingMessage)
        assert messages[0].ts == 42.0

    def test_oversized_message_raises(self):
        import struct

        reader = FrameReader()
        reader.feed(struct.pack("!I", 16 * 1024 * 1024 + 1))
        with pytest.raises(ValueError, match="exceeds maximum size"):
            reader.drain()
