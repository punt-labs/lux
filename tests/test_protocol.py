"""Tests for punt_lux.protocol — message types, serialization, framing."""

from __future__ import annotations

from typing import Any

import pytest

from punt_lux.protocol import (
    AckMessage,
    ButtonElement,
    CheckboxElement,
    ClearMessage,
    CollapsingHeaderElement,
    ColorPickerElement,
    ComboElement,
    DrawElement,
    FrameReader,
    GroupElement,
    ImageElement,
    InputTextElement,
    InteractionMessage,
    Message,
    Patch,
    PingMessage,
    PongMessage,
    RadioElement,
    ReadyMessage,
    SceneMessage,
    SeparatorElement,
    SliderElement,
    TabBarElement,
    TextElement,
    UpdateMessage,
    WindowElement,
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

    def test_slider_element(self):
        e = SliderElement(id="sl1", label="Volume", value=50.0, min=0.0, max=100.0)
        assert e.kind == "slider"
        assert e.value == 50.0
        assert not e.integer

    def test_slider_integer(self):
        e = SliderElement(id="sl2", label="Count", integer=True)
        assert e.integer

    def test_checkbox_element(self):
        e = CheckboxElement(id="cb1", label="Enable")
        assert e.kind == "checkbox"
        assert e.value is False

    def test_combo_element(self):
        e = ComboElement(id="co1", label="Choice", items=["A", "B"], selected=1)
        assert e.kind == "combo"
        assert e.items == ["A", "B"]
        assert e.selected == 1

    def test_input_text_element(self):
        e = InputTextElement(id="it1", label="Name", hint="Enter name")
        assert e.kind == "input_text"
        assert e.hint == "Enter name"
        assert e.value == ""

    def test_radio_element(self):
        e = RadioElement(id="r1", label="Pick", items=["X", "Y"])
        assert e.kind == "radio"
        assert e.selected == 0

    def test_color_picker_element(self):
        e = ColorPickerElement(id="cp1", label="Color")
        assert e.kind == "color_picker"
        assert e.value == "#FFFFFF"

    def test_draw_element(self):
        cmds: list[dict[str, Any]] = [{"cmd": "line", "p1": [0, 0], "p2": [10, 10]}]
        e = DrawElement(id="d1", commands=cmds)
        assert e.kind == "draw"
        assert e.width == 400
        assert e.height == 300
        assert e.bg_color is None
        assert len(e.commands) == 1

    def test_draw_element_defaults(self):
        e = DrawElement(id="d1")
        assert e.commands == []

    def test_group_element(self):
        child = TextElement(id="t1", content="hi")
        e = GroupElement(id="g1", layout="columns", children=[child])
        assert e.kind == "group"
        assert e.layout == "columns"
        assert len(e.children) == 1

    def test_group_element_defaults(self):
        e = GroupElement(id="g1")
        assert e.layout == "rows"
        assert e.children == []

    def test_tab_bar_element(self):
        e = TabBarElement(
            id="tb1",
            tabs=[{"label": "Tab A", "children": [TextElement(id="t1", content="A")]}],
        )
        assert e.kind == "tab_bar"
        assert len(e.tabs) == 1

    def test_collapsing_header_element(self):
        e = CollapsingHeaderElement(
            id="ch1",
            label="Details",
            default_open=True,
            children=[TextElement(id="t1", content="inside")],
        )
        assert e.kind == "collapsing_header"
        assert e.default_open is True
        assert e.label == "Details"

    def test_collapsing_header_defaults(self):
        e = CollapsingHeaderElement(id="ch1")
        assert e.label == ""
        assert e.default_open is False
        assert e.children == []

    def test_window_element(self):
        e = WindowElement(
            id="w1",
            title="Panel",
            x=100,
            y=50,
            width=400,
            height=300,
            children=[TextElement(id="t1", content="inside")],
        )
        assert e.kind == "window"
        assert e.title == "Panel"
        assert e.x == 100
        assert len(e.children) == 1

    def test_window_element_defaults(self):
        e = WindowElement(id="w1")
        assert e.title == ""
        assert e.x == 50.0
        assert e.y == 50.0
        assert e.width == 300.0
        assert e.height == 200.0
        assert e.no_move is False
        assert e.no_resize is False
        assert e.no_collapse is False
        assert e.no_title_bar is False
        assert e.no_scrollbar is False
        assert e.auto_resize is False
        assert e.children == []

    def test_window_element_flags(self):
        e = WindowElement(id="w1", no_move=True, no_resize=True, auto_resize=True)
        assert e.no_move is True
        assert e.no_resize is True
        assert e.auto_resize is True


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

    def test_slider_roundtrip(self):
        e = SliderElement(id="sl1", label="Vol", value=50.0, min=0.0, max=100.0)
        scene = SceneMessage(id="s1", elements=[e])
        d = message_to_dict(scene)
        restored = message_from_dict(d)
        assert isinstance(restored, SceneMessage)
        elem = restored.elements[0]
        assert isinstance(elem, SliderElement)
        assert elem.value == 50.0
        assert elem.format == "%.1f"

    def test_slider_integer_flag_roundtrip(self):
        e = SliderElement(id="sl2", label="N", integer=True)
        scene = SceneMessage(id="s1", elements=[e])
        d = message_to_dict(scene)
        assert d["elements"][0]["integer"] is True
        restored = message_from_dict(d)
        assert isinstance(restored, SceneMessage)
        assert isinstance(restored.elements[0], SliderElement)
        assert restored.elements[0].integer is True

    def test_slider_integer_false_excluded(self):
        e = SliderElement(id="sl3", label="X")
        scene = SceneMessage(id="s1", elements=[e])
        d = message_to_dict(scene)
        assert "integer" not in d["elements"][0]

    def test_checkbox_roundtrip(self):
        e = CheckboxElement(id="cb1", label="On", value=True)
        scene = SceneMessage(id="s1", elements=[e])
        d = message_to_dict(scene)
        restored = message_from_dict(d)
        assert isinstance(restored, SceneMessage)
        elem = restored.elements[0]
        assert isinstance(elem, CheckboxElement)
        assert elem.value is True

    def test_combo_roundtrip(self):
        e = ComboElement(id="co1", label="Pick", items=["A", "B", "C"], selected=2)
        scene = SceneMessage(id="s1", elements=[e])
        d = message_to_dict(scene)
        restored = message_from_dict(d)
        assert isinstance(restored, SceneMessage)
        elem = restored.elements[0]
        assert isinstance(elem, ComboElement)
        assert elem.items == ["A", "B", "C"]
        assert elem.selected == 2

    def test_input_text_roundtrip(self):
        e = InputTextElement(id="it1", label="Name", value="Alice", hint="who?")
        scene = SceneMessage(id="s1", elements=[e])
        d = message_to_dict(scene)
        restored = message_from_dict(d)
        assert isinstance(restored, SceneMessage)
        elem = restored.elements[0]
        assert isinstance(elem, InputTextElement)
        assert elem.value == "Alice"
        assert elem.hint == "who?"

    def test_input_text_hint_excluded_when_empty(self):
        e = InputTextElement(id="it2", label="X")
        scene = SceneMessage(id="s1", elements=[e])
        d = message_to_dict(scene)
        assert "hint" not in d["elements"][0]

    def test_radio_roundtrip(self):
        e = RadioElement(id="r1", label="Opt", items=["X", "Y"], selected=1)
        scene = SceneMessage(id="s1", elements=[e])
        d = message_to_dict(scene)
        restored = message_from_dict(d)
        assert isinstance(restored, SceneMessage)
        elem = restored.elements[0]
        assert isinstance(elem, RadioElement)
        assert elem.items == ["X", "Y"]
        assert elem.selected == 1

    def test_color_picker_roundtrip(self):
        e = ColorPickerElement(id="cp1", label="Bg", value="#FF0000")
        scene = SceneMessage(id="s1", elements=[e])
        d = message_to_dict(scene)
        restored = message_from_dict(d)
        assert isinstance(restored, SceneMessage)
        elem = restored.elements[0]
        assert isinstance(elem, ColorPickerElement)
        assert elem.value == "#FF0000"

    def test_draw_roundtrip(self):
        cmds: list[dict[str, Any]] = [
            {"cmd": "rect", "min": [10, 10], "max": [50, 50], "color": "#FF0000"},
        ]
        e = DrawElement(
            id="d1", width=200, height=100, bg_color="#000000", commands=cmds
        )
        scene = SceneMessage(id="s1", elements=[e])
        d = message_to_dict(scene)
        restored = message_from_dict(d)
        assert isinstance(restored, SceneMessage)
        elem = restored.elements[0]
        assert isinstance(elem, DrawElement)
        assert elem.width == 200
        assert elem.bg_color == "#000000"
        assert len(elem.commands) == 1

    def test_draw_bg_color_excluded_when_none(self):
        e = DrawElement(id="d1")
        scene = SceneMessage(id="s1", elements=[e])
        d = message_to_dict(scene)
        assert "bg_color" not in d["elements"][0]

    def test_group_roundtrip(self):
        e = GroupElement(
            id="g1",
            layout="columns",
            children=[
                TextElement(id="t1", content="Left"),
                ButtonElement(id="b1", label="Right"),
            ],
        )
        scene = SceneMessage(id="s1", elements=[e])
        d = message_to_dict(scene)
        restored = message_from_dict(d)
        assert isinstance(restored, SceneMessage)
        grp = restored.elements[0]
        assert isinstance(grp, GroupElement)
        assert grp.layout == "columns"
        assert len(grp.children) == 2
        assert isinstance(grp.children[0], TextElement)
        assert isinstance(grp.children[1], ButtonElement)

    def test_tab_bar_roundtrip(self):
        e = TabBarElement(
            id="tb1",
            tabs=[
                {
                    "label": "Tab 1",
                    "children": [TextElement(id="t1", content="Content 1")],
                },
                {
                    "label": "Tab 2",
                    "children": [
                        ButtonElement(id="b1", label="Action"),
                        SliderElement(id="sl1", label="Vol"),
                    ],
                },
            ],
        )
        scene = SceneMessage(id="s1", elements=[e])
        d = message_to_dict(scene)
        restored = message_from_dict(d)
        assert isinstance(restored, SceneMessage)
        tb = restored.elements[0]
        assert isinstance(tb, TabBarElement)
        assert len(tb.tabs) == 2
        assert tb.tabs[0]["label"] == "Tab 1"
        assert isinstance(tb.tabs[0]["children"][0], TextElement)
        assert len(tb.tabs[1]["children"]) == 2

    def test_collapsing_header_roundtrip(self):
        e = CollapsingHeaderElement(
            id="ch1",
            label="Advanced",
            default_open=True,
            children=[
                CheckboxElement(id="cb1", label="Debug"),
                SliderElement(id="sl1", label="Level"),
            ],
        )
        scene = SceneMessage(id="s1", elements=[e])
        d = message_to_dict(scene)
        restored = message_from_dict(d)
        assert isinstance(restored, SceneMessage)
        ch = restored.elements[0]
        assert isinstance(ch, CollapsingHeaderElement)
        assert ch.label == "Advanced"
        assert ch.default_open is True
        assert len(ch.children) == 2

    def test_collapsing_header_default_open_excluded_when_false(self):
        e = CollapsingHeaderElement(id="ch1", label="Section")
        scene = SceneMessage(id="s1", elements=[e])
        d = message_to_dict(scene)
        assert "default_open" not in d["elements"][0]

    def test_nested_group_in_tab_bar_roundtrip(self):
        inner = GroupElement(
            id="g1",
            layout="columns",
            children=[
                TextElement(id="t1", content="A"),
                TextElement(id="t2", content="B"),
            ],
        )
        outer = TabBarElement(
            id="tb1",
            tabs=[{"label": "Layout", "children": [inner]}],
        )
        scene = SceneMessage(id="s1", elements=[outer])
        d = message_to_dict(scene)
        restored = message_from_dict(d)
        assert isinstance(restored, SceneMessage)
        tb = restored.elements[0]
        assert isinstance(tb, TabBarElement)
        grp = tb.tabs[0]["children"][0]
        assert isinstance(grp, GroupElement)
        assert len(grp.children) == 2

    def test_window_roundtrip(self):
        e = WindowElement(
            id="w1",
            title="Settings",
            x=100,
            y=50,
            width=400,
            height=300,
            no_resize=True,
            children=[
                TextElement(id="t1", content="Hello from window"),
                SliderElement(id="sl1", label="Vol"),
                ButtonElement(id="b1", label="OK"),
            ],
        )
        scene = SceneMessage(id="s1", elements=[e])
        d = message_to_dict(scene)
        restored = message_from_dict(d)
        assert isinstance(restored, SceneMessage)
        win = restored.elements[0]
        assert isinstance(win, WindowElement)
        assert win.title == "Settings"
        assert win.x == 100
        assert win.width == 400
        assert win.no_resize is True
        assert win.no_move is False
        assert len(win.children) == 3

    def test_window_flags_excluded_when_false(self):
        e = WindowElement(id="w1")
        scene = SceneMessage(id="s1", elements=[e])
        d = message_to_dict(scene)
        elem_d = d["elements"][0]
        for flag in (
            "no_move",
            "no_resize",
            "no_collapse",
            "no_title_bar",
            "no_scrollbar",
            "auto_resize",
        ):
            assert flag not in elem_d

    def test_multiple_windows_roundtrip(self):
        w1 = WindowElement(
            id="w1",
            title="Left",
            x=10,
            y=10,
            children=[TextElement(id="t1", content="Panel 1")],
        )
        w2 = WindowElement(
            id="w2",
            title="Right",
            x=320,
            y=10,
            children=[TextElement(id="t2", content="Panel 2")],
        )
        scene = SceneMessage(id="s1", elements=[w1, w2])
        d = message_to_dict(scene)
        restored = message_from_dict(d)
        assert isinstance(restored, SceneMessage)
        assert len(restored.elements) == 2
        assert isinstance(restored.elements[0], WindowElement)
        assert isinstance(restored.elements[1], WindowElement)
        assert restored.elements[0].title == "Left"
        assert restored.elements[1].title == "Right"

    def test_window_with_nested_containers_roundtrip(self):
        grp = GroupElement(
            id="g1",
            layout="columns",
            children=[
                ButtonElement(id="b1", label="A"),
                ButtonElement(id="b2", label="B"),
            ],
        )
        win = WindowElement(
            id="w1",
            title="Complex",
            children=[
                grp,
                CollapsingHeaderElement(
                    id="ch1",
                    label="More",
                    children=[TextElement(id="t1", content="nested")],
                ),
            ],
        )
        scene = SceneMessage(id="s1", elements=[win])
        d = message_to_dict(scene)
        restored = message_from_dict(d)
        assert isinstance(restored, SceneMessage)
        r_win = restored.elements[0]
        assert isinstance(r_win, WindowElement)
        assert isinstance(r_win.children[0], GroupElement)
        assert isinstance(r_win.children[1], CollapsingHeaderElement)

    def test_deeply_nested_containers_roundtrip(self):
        leaf = TextElement(id="leaf", content="deep")
        ch = CollapsingHeaderElement(id="ch1", label="Inner", children=[leaf])
        grp = GroupElement(id="g1", children=[ch])
        scene = SceneMessage(id="s1", elements=[grp])
        d = message_to_dict(scene)
        restored = message_from_dict(d)
        assert isinstance(restored, SceneMessage)
        r_grp = restored.elements[0]
        assert isinstance(r_grp, GroupElement)
        r_ch = r_grp.children[0]
        assert isinstance(r_ch, CollapsingHeaderElement)
        r_leaf = r_ch.children[0]
        assert isinstance(r_leaf, TextElement)
        assert r_leaf.content == "deep"

    def test_mixed_interactive_scene_roundtrip(self):
        original = SceneMessage(
            id="s1",
            elements=[
                TextElement(id="t1", content="Settings"),
                SliderElement(id="sl1", label="Vol", value=75.0),
                CheckboxElement(id="cb1", label="Mute"),
                ComboElement(id="co1", label="Output", items=["Speakers", "Phones"]),
                InputTextElement(id="it1", label="Name"),
                RadioElement(id="r1", label="Mode", items=["A", "B"]),
                ColorPickerElement(id="cp1", label="Theme"),
                SeparatorElement(),
                ButtonElement(id="b1", label="Apply"),
            ],
        )
        d = message_to_dict(original)
        restored = message_from_dict(d)
        assert isinstance(restored, SceneMessage)
        assert len(restored.elements) == 9


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
