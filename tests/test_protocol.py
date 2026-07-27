"""Tests for punt_lux.protocol — message types, serialization, framing."""

from __future__ import annotations

import base64
import pickle
from typing import Any

import pytest

from punt_lux.display_client import agent_element_factory
from punt_lux.protocol import (
    AckMessage,
    ButtonElement,
    CheckboxElement,
    ClearMessage,
    ColorPickerElement,
    ComboElement,
    ConnectMessage,
    FrameReader,
    GroupElement,
    ImageElement,
    InputNumberElement,
    InputTextElement,
    IntrospectRequest,
    IntrospectResponse,
    ListScenesRequest,
    ListScenesResponse,
    MarkdownElement,
    MenuMessage,
    Message,
    ModalElement,
    PingMessage,
    PlotElement,
    PongMessage,
    ProgressElement,
    QueryRequest,
    QueryResponse,
    RadioElement,
    ReadyMessage,
    RegisterMenuMessage,
    RemoteEventHandlerInvocation,
    SceneMessage,
    ScreenshotRequest,
    ScreenshotResponse,
    SelectableElement,
    SeparatorElement,
    SliderElement,
    SpinnerElement,
    TextElement,
    ThemeMessage,
    TreeElement,
    UnknownMessage,
    decode_frame,
    encode_frame,
    encode_message,
    message_from_dict,
    message_to_dict,
)
from punt_lux.protocol.elements.plot_series import PlotSeries
from punt_lux.protocol.elements.tree_node import TreeNode

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
        # PY-TS-14: id is str (anonymous separators use "").
        assert e.id == ""

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

    def test_group_element(self):
        child = TextElement(id="t1", content="hi")
        e = GroupElement(id="g1", layout="columns", children=[child])
        assert e.kind == "group"
        assert e.layout == "columns"
        assert len(e.children) == 1

    def test_group_element_defaults(self):
        e = GroupElement(id="g1")
        assert e.layout == "rows"
        assert e.children == ()

    def test_selectable_element(self):
        e = SelectableElement(id="s1", label="Item A", selected=True)
        assert e.kind == "selectable"
        assert e.selected is True

    def test_selectable_defaults(self):
        e = SelectableElement(id="s1", label="X")
        assert e.selected is False

    def test_tree_element(self):
        nodes = (
            TreeNode(
                label="src",
                children=(TreeNode(label="main.py"), TreeNode(label="lib.py")),
            ),
            TreeNode(label="README.md"),
        )
        e = TreeElement(id="tr1", label="Project", nodes=nodes)
        assert e.kind == "tree"
        assert e.label == "Project"
        assert len(e.nodes) == 2

    def test_tree_element_defaults(self):
        e = TreeElement(id="tr1")
        assert e.label == ""
        assert e.nodes == ()
        assert e.flat is False

    def test_tree_element_flat(self):
        e = TreeElement(id="tr1", label="Info", flat=True)
        assert e.flat is True

    def test_plot_element(self):
        series = (PlotSeries("y", "line", (1.0, 2.0, 3.0), (10.0, 20.0, 15.0)),)
        e = PlotElement(id="p1", title="Trend", series=series)
        assert e.kind == "plot"
        assert e.title == "Trend"
        assert len(e.series) == 1
        assert e.width == -1
        assert e.height == 300

    def test_plot_element_defaults(self):
        e = PlotElement(id="p1")
        assert e.title == ""
        assert e.x_label == ""
        assert e.y_label == ""
        assert e.width == -1
        assert e.height == 300
        assert e.series == ()

    def test_progress_element(self):
        e = ProgressElement(id="pg1", fraction=0.73, label="73%")
        assert e.kind == "progress"
        assert e.fraction == 0.73
        assert e.label == "73%"

    def test_progress_element_defaults(self):
        e = ProgressElement(id="pg1")
        assert e.fraction == 0.0
        assert e.label == ""

    def test_spinner_element(self):
        e = SpinnerElement(id="sp1", label="Loading", radius=20.0, color="#FF0000")
        assert e.kind == "spinner"
        assert e.radius == 20.0
        assert e.color == "#FF0000"

    def test_spinner_element_defaults(self):
        e = SpinnerElement(id="sp1")
        assert e.label == ""
        assert e.radius == 16.0
        assert e.color == "#3399FF"

    def test_markdown_element(self):
        e = MarkdownElement(id="md1", content="# Hello\n\n**Bold**")
        assert e.kind == "markdown"
        assert e.content == "# Hello\n\n**Bold**"

    def test_tooltip_field(self):
        e = TextElement(id="t1", content="hi", tooltip="help text")
        assert e.tooltip == "help text"

    def test_tooltip_default_is_none(self):
        e = ButtonElement(id="b1", label="OK")
        assert e.tooltip is None

    # -- InputNumberElement -------------------------------------------------

    def test_input_number_element(self):
        e = InputNumberElement(id="in1", label="Price", value=9.99, step=0.01)
        assert e.kind == "input_number"
        assert e.value == 9.99
        assert e.step == 0.01
        assert not e.integer

    def test_input_number_integer(self):
        e = InputNumberElement(id="in2", label="Qty", integer=True, min=1, max=100)
        assert e.integer
        assert e.min == 1
        assert e.max == 100

    def test_input_number_defaults(self):
        e = InputNumberElement(id="in3", label="X")
        assert e.value == 0.0
        assert e.min is None
        assert e.max is None
        assert e.step is None
        assert e.format == "%.3f"
        assert not e.integer

    # -- ButtonElement extensions ------------------------------------------

    def test_button_arrow(self):
        e = ButtonElement(id="b1", label="Prev", arrow="left")
        assert e.arrow == "left"
        assert not e.small

    def test_button_small(self):
        e = ButtonElement(id="b2", label="Save", small=True)
        assert e.small
        assert e.arrow is None

    def test_button_defaults_unchanged(self):
        e = ButtonElement(id="b3", label="OK")
        assert e.arrow is None
        assert not e.small
        assert not e.disabled

    # -- ColorPickerElement extensions -------------------------------------

    def test_color_picker_alpha(self):
        e = ColorPickerElement(id="cp1", label="BG", alpha=True, value="#FF0000FF")
        assert e.alpha
        assert not e.picker
        assert e.value == "#FF0000FF"

    def test_color_picker_full_picker(self):
        e = ColorPickerElement(id="cp2", label="Accent", picker=True)
        assert e.picker
        assert not e.alpha

    def test_color_picker_defaults_unchanged(self):
        e = ColorPickerElement(id="cp3", label="Color")
        assert not e.alpha
        assert not e.picker
        assert e.value == "#FFFFFF"

    # -- ModalElement ------------------------------------------------------

    def test_modal_element(self):
        child = TextElement(id="t1", content="Are you sure?")
        e = ModalElement(id="m1", title="Confirm")
        e.install_children((child,))
        assert e.kind == "modal"
        assert e.title == "Confirm"
        assert e.open is True
        assert len(e.children) == 1

    def test_modal_defaults(self):
        e = ModalElement(id="m2")
        assert e.title == ""
        assert e.open is True
        assert e.children == ()


# ---------------------------------------------------------------------------
# Message construction
# ---------------------------------------------------------------------------


class TestMessages:
    def test_scene_message(self):
        msg = SceneMessage(
            id="s1",
            elements=[TextElement(id="t1", content="hi")],
            frame_id="s1",
            layout="rows",
            title="Test",
        )
        assert msg.type == "scene"
        assert len(msg.elements) == 1

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
        msg = RemoteEventHandlerInvocation(element_id="b1", action="click", value=42)
        assert msg.value == 42

    def test_pong_message(self):
        msg = PongMessage(ts=1.0, display_ts=2.0)
        assert msg.display_ts == 2.0

    def test_menu_message(self):
        menus = [
            {
                "label": "Tools",
                "items": [
                    {"label": "Run Script", "id": "run_script"},
                    {"label": "---"},
                    {"label": "Settings", "id": "settings", "shortcut": "Ctrl+,"},
                ],
            },
        ]
        msg = MenuMessage(menus=menus)
        assert msg.type == "menu"
        assert len(msg.menus) == 1
        assert msg.menus[0]["label"] == "Tools"

    def test_menu_message_defaults(self):
        msg = MenuMessage(menus=[])
        assert msg.type == "menu"
        assert msg.menus == []

    def test_menu_roundtrip(self):
        menus = [
            {
                "label": "Custom",
                "items": [
                    {"label": "Action", "id": "act1", "enabled": False},
                ],
            },
        ]
        original = MenuMessage(menus=menus)
        d = message_to_dict(original)
        restored = message_from_dict(d)
        assert isinstance(restored, MenuMessage)
        assert restored.menus == menus

    def test_theme_message_roundtrip(self):
        original = ThemeMessage(theme="imgui_colors_light")
        d = message_to_dict(original)
        restored = message_from_dict(d)
        assert isinstance(restored, ThemeMessage)
        assert restored.theme == "imgui_colors_light"

    def test_register_menu_message(self):
        items = [
            {"label": "Run Script", "id": "run_script"},
            {"label": "Settings", "id": "settings", "shortcut": "Ctrl+,"},
        ]
        msg = RegisterMenuMessage(items=items)
        assert msg.type == "register_menu"
        assert len(msg.items) == 2
        assert msg.items[0]["label"] == "Run Script"

    def test_register_menu_roundtrip(self):
        items: list[dict[str, Any]] = [
            {"label": "Deploy", "id": "deploy", "enabled": False},
            {"label": "Test", "id": "test", "shortcut": "Ctrl+T", "icon": "play"},
        ]
        original = RegisterMenuMessage(items=items)
        d = message_to_dict(original)
        assert d["type"] == "register_menu"
        assert d["items"] == items
        restored = message_from_dict(d)
        assert isinstance(restored, RegisterMenuMessage)
        assert restored.items == items

    def test_register_menu_from_dict(self):
        d = {
            "type": "register_menu",
            "items": [{"label": "Foo", "id": "foo"}],
        }
        msg = message_from_dict(d)
        assert isinstance(msg, RegisterMenuMessage)
        assert msg.items == [{"label": "Foo", "id": "foo"}]

    def test_register_menu_from_dict_empty_items(self):
        d = {"type": "register_menu"}
        msg = message_from_dict(d)
        assert isinstance(msg, RegisterMenuMessage)
        assert msg.items == []


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
            frame_id="s1",
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

    def test_framed_scene_roundtrip(self):
        original = SceneMessage(
            id="s1",
            elements=[TextElement(id="t1", content="hello")],
            frame_id="beads-explorer",
            frame_title="Beads Explorer",
        )
        d = message_to_dict(original)
        assert d["frame_id"] == "beads-explorer"
        assert d["frame_title"] == "Beads Explorer"
        restored = message_from_dict(d)
        assert isinstance(restored, SceneMessage)
        assert restored.frame_id == "beads-explorer"
        assert restored.frame_title == "Beads Explorer"

    def test_framed_scene_with_size_and_flags_roundtrip(self):
        original = SceneMessage(
            id="s1",
            elements=[TextElement(id="t1", content="hello")],
            frame_id="vox-booth",
            frame_title="Vox Booth",
            frame_size=(340, 120),
            frame_flags={"no_resize": True, "auto_resize": True},
        )
        d = message_to_dict(original)
        assert d["frame_size"] == [340, 120]
        assert d["frame_flags"] == {"no_resize": True, "auto_resize": True}
        restored = message_from_dict(d)
        assert isinstance(restored, SceneMessage)
        assert restored.frame_size == (340, 120)
        assert restored.frame_flags == {"no_resize": True, "auto_resize": True}

    def test_framed_scene_without_size_omits_fields(self):
        original = SceneMessage(
            id="s1",
            elements=[TextElement(id="t1", content="hello")],
            frame_id="f1",
        )
        d = message_to_dict(original)
        assert "frame_size" not in d
        assert "frame_flags" not in d
        restored = message_from_dict(d)
        assert isinstance(restored, SceneMessage)
        assert restored.frame_size is None
        assert restored.frame_flags is None

    def test_scene_decode_rejects_an_out_of_set_layout(self):
        # The layout field is a Literal; decode must reject an out-of-set value
        # with the same named error the RenderRequest boundary raises, not smuggle
        # it in behind an Any.
        with pytest.raises(ValueError, match="layout must be single/rows/columns/grid"):
            SceneMessage.from_dict(
                {"id": "s1", "frame_id": "s1", "elements": [], "layout": "diagonal"}
            )

    def test_scene_decode_accepts_each_valid_layout(self):
        for value in ("single", "rows", "columns", "grid"):
            restored = SceneMessage.from_dict(
                {"id": "s1", "frame_id": "s1", "elements": [], "layout": value}
            )
            assert restored.layout == value

    def test_scene_decode_rejects_a_missing_elements_field(self):
        # Omission is not removal: a wire dict with no elements field is malformed,
        # not the empty-push remove signal.
        with pytest.raises(ValueError, match="scene elements must be a present list"):
            SceneMessage.from_dict({"id": "s1", "frame_id": "s1"})

    def test_scene_decode_rejects_a_non_list_elements_field(self):
        with pytest.raises(ValueError, match="scene elements must be a present list"):
            SceneMessage.from_dict({"id": "s1", "frame_id": "s1", "elements": "nope"})

    def test_scene_decode_accepts_an_explicit_empty_elements_list(self):
        # An explicit [] is the intentional empty-push removal signal — kept valid.
        restored = SceneMessage.from_dict(
            {"id": "s1", "frame_id": "s1", "elements": []}
        )
        assert restored.elements == []

    def test_scene_decode_rejects_a_non_dict_element_entry(self):
        # Each entry must be a dict — a bare string decodes to a named error, not a
        # raw TypeError from probing "_pickled" in a non-dict.
        with pytest.raises(ValueError, match="scene element must be a dict"):
            SceneMessage.from_dict({"id": "s1", "frame_id": "s1", "elements": ["oops"]})

    def test_scene_decode_rejects_a_non_str_pickled_entry(self):
        with pytest.raises(ValueError, match="scene element _pickled must be a str"):
            SceneMessage.from_dict(
                {"id": "s1", "frame_id": "s1", "elements": [{"_pickled": 123}]}
            )

    def test_scene_decode_rejects_a_missing_id(self):
        # A required str field decodes to a named error, not a bare KeyError.
        with pytest.raises(ValueError, match="scene field 'id' must be a str"):
            SceneMessage.from_dict({"frame_id": "s1", "elements": []})

    def test_scene_decode_rejects_a_missing_frame_id(self):
        with pytest.raises(ValueError, match="scene field 'frame_id' must be a str"):
            SceneMessage.from_dict({"id": "s1", "elements": []})

    def test_scene_decode_rejects_truncated_base64_pickle(self):
        # A corrupt pickle payload must not escape as binascii/EOF/UnpicklingError
        # (the display's reader only catches ValueError/KeyError/TypeError).
        with pytest.raises(ValueError, match="_pickled is not decodable"):
            self._decode_pickled("!!!not base64!!!")

    def test_scene_decode_rejects_valid_base64_truncated_pickle(self):
        truncated = base64.b64encode(pickle.dumps([1, 2, 3])[:5]).decode("ascii")
        with pytest.raises(ValueError, match="_pickled is not decodable"):
            self._decode_pickled(truncated)

    def test_scene_decode_rejects_garbage_pickle_bytes(self):
        garbage = base64.b64encode(b"not a pickled element").decode("ascii")
        with pytest.raises(ValueError, match="_pickled is not decodable"):
            self._decode_pickled(garbage)

    @staticmethod
    def _decode_pickled(payload: str) -> None:
        SceneMessage.from_dict(
            {"id": "s1", "frame_id": "s1", "elements": [{"_pickled": payload}]}
        )

    def test_connect_message_roundtrip(self):
        original = ConnectMessage(name="quarry")
        d = message_to_dict(original)
        assert d["type"] == "connect"
        assert d["name"] == "quarry"
        restored = message_from_dict(d)
        assert isinstance(restored, ConnectMessage)
        assert restored.name == "quarry"

    @pytest.mark.parametrize(
        "msg",
        [
            pytest.param(
                SceneMessage(
                    id="s1",
                    elements=[TextElement(id="t1", content="hello")],
                    frame_id="s1",
                    layout="rows",
                    title="Test",
                ),
                id="SceneMessage",
            ),
            pytest.param(ClearMessage(), id="ClearMessage"),
            pytest.param(PingMessage(ts=1.0), id="PingMessage"),
            pytest.param(IntrospectRequest(scene_id="s1"), id="IntrospectRequest"),
            pytest.param(
                IntrospectResponse(
                    scene_id="s1",
                    elements=[{"kind": "text", "id": "t1", "content": "hi"}],
                ),
                id="IntrospectResponse",
            ),
            pytest.param(ListScenesRequest(), id="ListScenesRequest"),
            pytest.param(
                ListScenesResponse(
                    scenes=[{"scene_id": "s1", "element_count": 1}],
                    frames=[{"frame_id": "f1", "title": "Main"}],
                ),
                id="ListScenesResponse",
            ),
            pytest.param(ScreenshotRequest(), id="ScreenshotRequest"),
            pytest.param(
                ScreenshotResponse(path="/tmp/shot.png"),
                id="ScreenshotResponse",
            ),
            pytest.param(
                MenuMessage(
                    menus=[{"label": "Tools", "items": [{"label": "Run", "id": "r"}]}]
                ),
                id="MenuMessage",
            ),
            pytest.param(ThemeMessage(theme="imgui_colors_dark"), id="ThemeMessage"),
            pytest.param(
                RegisterMenuMessage(items=[{"label": "Deploy", "id": "deploy"}]),
                id="RegisterMenuMessage",
            ),
            pytest.param(ConnectMessage(name="quarry"), id="ConnectMessage"),
            pytest.param(
                QueryRequest(method="get_theme", params={"key": "bg"}),
                id="QueryRequest",
            ),
            pytest.param(
                ReadyMessage(version="0.1", capabilities=["implot"]),
                id="ReadyMessage",
            ),
            pytest.param(
                AckMessage(scene_id="s1", ts=2.0, error=None),
                id="AckMessage",
            ),
            pytest.param(
                RemoteEventHandlerInvocation(
                    element_id="b1", action="click", value=42, scene_id="s1"
                ),
                id="RemoteEventHandlerInvocation",
            ),
            pytest.param(PongMessage(ts=1.0, display_ts=2.0), id="PongMessage"),
            pytest.param(
                QueryResponse(
                    method="get_theme",
                    result={"theme": "dark"},
                    error=None,
                ),
                id="QueryResponse",
            ),
            pytest.param(
                UnknownMessage(raw_type="future_v2_msg", data={"x": 1, "y": "hello"}),
                id="UnknownMessage",
            ),
        ],
    )
    def test_all_message_types_roundtrip(self, msg: Message) -> None:
        d = message_to_dict(msg)
        restored = message_from_dict(d)
        assert type(restored) is type(msg)

    def test_unknown_message_type_returns_passthrough(self):
        msg = message_from_dict({"type": "bogus", "data": 42})
        assert isinstance(msg, UnknownMessage)
        assert msg.raw_type == "bogus"
        assert msg.data == {"type": "bogus", "data": 42}

    def test_missing_message_type_raises(self):
        with pytest.raises(ValueError, match="missing or invalid"):
            message_from_dict({"data": 42})

    def test_empty_message_type_raises(self):
        with pytest.raises(ValueError, match="missing or invalid"):
            message_from_dict({"type": "", "data": 42})

    def test_non_string_message_type_raises(self):
        with pytest.raises(ValueError, match="missing or invalid"):
            message_from_dict({"type": 123})

    def test_unknown_message_roundtrip(self):
        data = {"type": "future_type", "x": 1}
        msg = UnknownMessage(raw_type="future_type", data=data)
        d = message_to_dict(msg)
        assert d == {"type": "future_type", "x": 1}

    def test_unknown_message_serializer_forces_type(self):
        msg = UnknownMessage(raw_type="my_type", data={})
        d = message_to_dict(msg)
        assert d == {"type": "my_type"}

    def test_unknown_element_kind_raises(self):
        with pytest.raises(ValueError, match="no decoder for kind='bogus'"):
            message_from_dict(
                {
                    "type": "scene",
                    "id": "s1",
                    "elements": [{"kind": "bogus", "id": "x"}],
                }
            )

    def test_strip_none_fields(self):
        msg = SceneMessage(id="s1", elements=[], title=None, frame_id="s1")
        d = message_to_dict(msg)
        assert "title" not in d

    def test_button_disabled_included(self):
        e = ButtonElement(id="b1", label="X", disabled=True)
        scene = SceneMessage(id="s1", elements=[e], frame_id="s1")
        d = message_to_dict(scene)
        # ABC elements use native serialization — roundtrip preserves fields
        assert "_pickled" in d["elements"][0]
        restored = message_from_dict(d)
        assert isinstance(restored, SceneMessage)
        btn = restored.elements[0]
        assert isinstance(btn, ButtonElement)
        assert btn.disabled is True

    def test_button_disabled_false_excluded(self):
        e = ButtonElement(id="b1", label="X", disabled=False)
        scene = SceneMessage(id="s1", elements=[e], frame_id="s1")
        d = message_to_dict(scene)
        # ABC elements use native serialization — roundtrip preserves fields
        restored = message_from_dict(d)
        assert isinstance(restored, SceneMessage)
        btn = restored.elements[0]
        assert isinstance(btn, ButtonElement)
        assert btn.disabled is False

    def test_slider_roundtrip(self):
        e = SliderElement(id="sl1", label="Vol", value=50.0, min=0.0, max=100.0)
        scene = SceneMessage(id="s1", elements=[e], frame_id="s1")
        d = message_to_dict(scene)
        restored = message_from_dict(d)
        assert isinstance(restored, SceneMessage)
        elem = restored.elements[0]
        assert isinstance(elem, SliderElement)
        assert elem.value == 50.0
        assert elem.format == "%.1f"

    def test_slider_integer_flag_roundtrip(self):
        # ABC slider crosses as a pickled entry, so assert the flag via the
        # restored element, not the wire dict; the Level-1 JSON shape carries it.
        e = SliderElement(id="sl2", label="N", integer=True)
        assert e.to_dict()["integer"] is True
        scene = SceneMessage(id="s1", elements=[e], frame_id="s1")
        restored = message_from_dict(message_to_dict(scene))
        assert isinstance(restored, SceneMessage)
        assert isinstance(restored.elements[0], SliderElement)
        assert restored.elements[0].integer is True

    def test_slider_integer_false_excluded(self):
        # The default integer=False is omitted from the Level-1 JSON shape.
        e = SliderElement(id="sl3", label="X")
        assert "integer" not in e.to_dict()

    def test_checkbox_roundtrip(self):
        e = CheckboxElement(id="cb1", label="On", value=True)
        scene = SceneMessage(id="s1", elements=[e], frame_id="s1")
        d = message_to_dict(scene)
        restored = message_from_dict(d)
        assert isinstance(restored, SceneMessage)
        elem = restored.elements[0]
        assert isinstance(elem, CheckboxElement)
        assert elem.value is True

    def test_combo_roundtrip(self):
        e = ComboElement(id="co1", label="Pick", items=["A", "B", "C"], selected=2)
        scene = SceneMessage(id="s1", elements=[e], frame_id="s1")
        d = message_to_dict(scene)
        restored = message_from_dict(d)
        assert isinstance(restored, SceneMessage)
        elem = restored.elements[0]
        assert isinstance(elem, ComboElement)
        assert elem.items == ["A", "B", "C"]
        assert elem.selected == 2

    def test_input_text_roundtrip(self):
        e = InputTextElement(id="it1", label="Name", value="Alice", hint="who?")
        scene = SceneMessage(id="s1", elements=[e], frame_id="s1")
        d = message_to_dict(scene)
        restored = message_from_dict(d)
        assert isinstance(restored, SceneMessage)
        elem = restored.elements[0]
        assert isinstance(elem, InputTextElement)
        assert elem.value == "Alice"
        assert elem.hint == "who?"

    def test_input_text_hint_excluded_when_empty(self):
        e = InputTextElement(id="it2", label="X")
        scene = SceneMessage(id="s1", elements=[e], frame_id="s1")
        d = message_to_dict(scene)
        assert "hint" not in d["elements"][0]

    def test_radio_roundtrip(self):
        e = RadioElement(id="r1", label="Opt", items=["X", "Y"], selected=1)
        scene = SceneMessage(id="s1", elements=[e], frame_id="s1")
        d = message_to_dict(scene)
        restored = message_from_dict(d)
        assert isinstance(restored, SceneMessage)
        elem = restored.elements[0]
        assert isinstance(elem, RadioElement)
        assert elem.items == ["X", "Y"]
        assert elem.selected == 1

    def test_color_picker_roundtrip(self):
        e = ColorPickerElement(id="cp1", label="Bg", value="#FF0000")
        scene = SceneMessage(id="s1", elements=[e], frame_id="s1")
        d = message_to_dict(scene)
        restored = message_from_dict(d)
        assert isinstance(restored, SceneMessage)
        elem = restored.elements[0]
        assert isinstance(elem, ColorPickerElement)
        assert elem.value == "#FF0000"

    def test_group_roundtrip(self):
        e = GroupElement(
            id="g1",
            layout="columns",
            children=[
                TextElement(id="t1", content="Left"),
                ButtonElement(id="b1", label="Right"),
            ],
        )
        scene = SceneMessage(id="s1", elements=[e], frame_id="s1")
        d = message_to_dict(scene)
        restored = message_from_dict(d)
        assert isinstance(restored, SceneMessage)
        grp = restored.elements[0]
        assert isinstance(grp, GroupElement)
        assert grp.layout == "columns"
        assert len(grp.children) == 2
        assert isinstance(grp.children[0], TextElement)
        assert isinstance(grp.children[1], ButtonElement)

    def test_selectable_roundtrip(self):
        e = SelectableElement(id="s1", label="Option A", selected=True)
        scene = SceneMessage(id="s1", elements=[e], frame_id="s1")
        d = message_to_dict(scene)
        restored = message_from_dict(d)
        assert isinstance(restored, SceneMessage)
        elem = restored.elements[0]
        assert isinstance(elem, SelectableElement)
        assert elem.label == "Option A"
        assert elem.selected is True

    def test_tree_roundtrip(self):
        nodes = (
            TreeNode(
                label="src",
                children=(TreeNode(label="main.py"), TreeNode(label="utils.py")),
            ),
            TreeNode(label="README.md"),
        )
        e = TreeElement(id="tr1", label="Project", nodes=nodes)
        scene = SceneMessage(id="s1", elements=[e], frame_id="s1")
        d = message_to_dict(scene)
        restored = message_from_dict(d)
        assert isinstance(restored, SceneMessage)
        tree = restored.elements[0]
        assert isinstance(tree, TreeElement)
        assert tree.label == "Project"
        assert len(tree.nodes) == 2
        assert tree.nodes[0].label == "src"
        assert len(tree.nodes[0].children) == 2

    def test_tree_flat_roundtrip(self):
        e = TreeElement(
            id="tr1",
            label="Details",
            nodes=(TreeNode(label="info", children=(TreeNode(label="value"),)),),
            flat=True,
        )
        scene = SceneMessage(id="s1", elements=[e], frame_id="s1")
        d = message_to_dict(scene)
        restored = message_from_dict(d)
        assert isinstance(restored, SceneMessage)
        tree = restored.elements[0]
        assert isinstance(tree, TreeElement)
        assert tree.flat is True

    def test_tree_flat_false_not_serialized(self):
        """flat=False should not appear in the wire dict (default omission)."""
        e = TreeElement(id="tr1", label="X")
        d = message_to_dict(SceneMessage(id="s1", elements=[e], frame_id="s1"))
        elem_dict = d["elements"][0]
        assert "flat" not in elem_dict

    def test_tree_empty_nodes_roundtrip(self):
        e = TreeElement(id="tr1", label="Empty")
        scene = SceneMessage(id="s1", elements=[e], frame_id="s1")
        d = message_to_dict(scene)
        restored = message_from_dict(d)
        assert isinstance(restored, SceneMessage)
        tree = restored.elements[0]
        assert isinstance(tree, TreeElement)
        assert tree.nodes == ()

    def test_plot_roundtrip(self):
        series = (
            PlotSeries("line1", "line", (1.0, 2.0, 3.0), (10.0, 20.0, 15.0)),
            PlotSeries("pts", "scatter", (1.0, 2.0), (5.0, 8.0)),
        )
        e = PlotElement(
            id="p1",
            title="My Plot",
            x_label="X",
            y_label="Y",
            width=500,
            height=400,
            series=series,
        )
        scene = SceneMessage(id="s1", elements=[e], frame_id="s1")
        d = message_to_dict(scene)
        restored = message_from_dict(d)
        assert isinstance(restored, SceneMessage)
        plot = restored.elements[0]
        assert isinstance(plot, PlotElement)
        assert plot.title == "My Plot"
        assert plot.x_label == "X"
        assert plot.y_label == "Y"
        assert plot.width == 500
        assert plot.height == 400
        assert len(plot.series) == 2

    def test_plot_empty_roundtrip(self):
        e = PlotElement(id="p1")
        scene = SceneMessage(id="s1", elements=[e], frame_id="s1")
        d = message_to_dict(scene)
        restored = message_from_dict(d)
        assert isinstance(restored, SceneMessage)
        plot = restored.elements[0]
        assert isinstance(plot, PlotElement)
        assert plot.series == ()
        assert plot.title == ""

    def test_progress_roundtrip(self):
        e = ProgressElement(id="pg1", fraction=0.5, label="Half")
        scene = SceneMessage(id="s1", elements=[e], frame_id="s1")
        d = message_to_dict(scene)
        restored = message_from_dict(d)
        assert isinstance(restored, SceneMessage)
        elem = restored.elements[0]
        assert isinstance(elem, ProgressElement)
        assert elem.fraction == 0.5
        assert elem.label == "Half"

    def test_progress_label_excluded_when_empty(self):
        e = ProgressElement(id="pg1", fraction=0.3)
        scene = SceneMessage(id="s1", elements=[e], frame_id="s1")
        d = message_to_dict(scene)
        assert "label" not in d["elements"][0]

    def test_spinner_roundtrip(self):
        e = SpinnerElement(id="sp1", label="Wait", radius=20.0, color="#FF0000")
        scene = SceneMessage(id="s1", elements=[e], frame_id="s1")
        d = message_to_dict(scene)
        restored = message_from_dict(d)
        assert isinstance(restored, SceneMessage)
        elem = restored.elements[0]
        assert isinstance(elem, SpinnerElement)
        assert elem.label == "Wait"
        assert elem.radius == 20.0
        assert elem.color == "#FF0000"

    def test_spinner_label_excluded_when_empty(self):
        e = SpinnerElement(id="sp1")
        scene = SceneMessage(id="s1", elements=[e], frame_id="s1")
        d = message_to_dict(scene)
        assert "label" not in d["elements"][0]

    def test_markdown_roundtrip(self):
        e = MarkdownElement(id="md1", content="# Title\n\nParagraph.")
        scene = SceneMessage(id="s1", elements=[e], frame_id="s1")
        d = message_to_dict(scene)
        restored = message_from_dict(d)
        assert isinstance(restored, SceneMessage)
        elem = restored.elements[0]
        assert isinstance(elem, MarkdownElement)
        assert elem.content == "# Title\n\nParagraph."

    def test_tooltip_roundtrip(self):
        e = TextElement(id="t1", content="hover me", tooltip="help")
        scene = SceneMessage(id="s1", elements=[e], frame_id="s1")
        d = message_to_dict(scene)
        # ABC elements use native serialization — roundtrip preserves fields
        restored = message_from_dict(d)
        assert isinstance(restored, SceneMessage)
        txt = restored.elements[0]
        assert isinstance(txt, TextElement)
        assert txt.tooltip == "help"

    def test_tooltip_excluded_when_none(self):
        e = TextElement(id="t1", content="no tip")
        scene = SceneMessage(id="s1", elements=[e], frame_id="s1")
        d = message_to_dict(scene)
        # ABC elements use native serialization — roundtrip preserves fields
        restored = message_from_dict(d)
        assert isinstance(restored, SceneMessage)
        txt = restored.elements[0]
        assert isinstance(txt, TextElement)
        assert txt.tooltip is None

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
            frame_id="s1",
        )
        d = message_to_dict(original)
        restored = message_from_dict(d)
        assert isinstance(restored, SceneMessage)
        assert len(restored.elements) == 9

    # -- element_from_dict for new/extended types --------------------------

    def test_input_number_from_dict(self):
        d = {
            "kind": "input_number",
            "id": "in1",
            "label": "Price",
            "value": 9.99,
            "min": 0,
            "max": 100,
            "step": 0.01,
            "format": "%.2f",
        }
        e = agent_element_factory().element_from_dict(d)
        assert isinstance(e, InputNumberElement)
        assert e.value == 9.99
        assert e.min == 0
        assert e.max == 100
        assert e.step == 0.01
        assert e.format == "%.2f"
        assert not e.integer

    def test_input_number_from_dict_integer(self):
        d = {"kind": "input_number", "id": "qty", "label": "Qty", "integer": True}
        e = agent_element_factory().element_from_dict(d)
        assert isinstance(e, InputNumberElement)
        assert e.integer
        assert e.value == 0.0

    def test_input_number_from_dict_defaults(self):
        d = {"kind": "input_number", "id": "x", "label": "X"}
        e = agent_element_factory().element_from_dict(d)
        assert isinstance(e, InputNumberElement)
        assert e.min is None
        assert e.max is None
        assert e.step is None

    def test_button_from_dict_arrow(self):
        d = {"kind": "button", "id": "b1", "label": "Prev", "arrow": "left"}
        e = agent_element_factory().element_from_dict(d)
        assert isinstance(e, ButtonElement)
        assert e.arrow == "left"
        assert not e.small

    def test_button_from_dict_small(self):
        d = {"kind": "button", "id": "b2", "label": "Save", "small": True}
        e = agent_element_factory().element_from_dict(d)
        assert isinstance(e, ButtonElement)
        assert e.small

    def test_button_from_dict_backwards_compat(self):
        d = {"kind": "button", "id": "b3", "label": "OK"}
        e = agent_element_factory().element_from_dict(d)
        assert isinstance(e, ButtonElement)
        assert e.arrow is None
        assert not e.small

    def test_color_picker_from_dict_alpha(self):
        d = {
            "kind": "color_picker",
            "id": "cp1",
            "label": "BG",
            "value": "#FF0000FF",
            "alpha": True,
        }
        e = agent_element_factory().element_from_dict(d)
        assert isinstance(e, ColorPickerElement)
        assert e.alpha
        assert not e.picker

    def test_color_picker_from_dict_picker(self):
        d = {"kind": "color_picker", "id": "cp2", "label": "Accent", "picker": True}
        e = agent_element_factory().element_from_dict(d)
        assert isinstance(e, ColorPickerElement)
        assert e.picker

    def test_color_picker_from_dict_backwards_compat(self):
        d = {"kind": "color_picker", "id": "cp3", "label": "Color"}
        e = agent_element_factory().element_from_dict(d)
        assert isinstance(e, ColorPickerElement)
        assert not e.alpha
        assert not e.picker

    def test_modal_from_dict(self):
        d = {
            "kind": "modal",
            "id": "m1",
            "title": "Confirm",
            "open": True,
            "children": [
                {"kind": "text", "id": "t1", "content": "Sure?"},
                {"kind": "button", "id": "b1", "label": "Yes"},
            ],
        }
        e = agent_element_factory().element_from_dict(d)
        assert isinstance(e, ModalElement)
        assert e.title == "Confirm"
        assert e.open is True
        assert len(e.children) == 2
        assert isinstance(e.children[0], TextElement)
        assert isinstance(e.children[1], ButtonElement)

    def test_modal_from_dict_defaults(self):
        d = {"kind": "modal", "id": "m2"}
        e = agent_element_factory().element_from_dict(d)
        assert isinstance(e, ModalElement)
        assert e.title == ""
        assert e.open is True
        assert e.children == ()

    def test_modal_open_false_roundtrip(self):
        original = SceneMessage(
            id="s1",
            elements=[ModalElement(id="m1", title="X", open=False)],
            frame_id="s1",
        )
        d = message_to_dict(original)
        restored = message_from_dict(d)
        assert isinstance(restored, SceneMessage)
        modal = restored.elements[0]
        assert isinstance(modal, ModalElement)
        assert modal.open is False

    def test_modal_scene_roundtrip(self):
        built = ModalElement(id="m1", title="Confirm")
        built.install_children(
            (
                TextElement(id="t1", content="Delete?"),
                ButtonElement(id="b1", label="Yes", action="confirm"),
            )
        )
        original = SceneMessage(id="s1", elements=[built], frame_id="s1")
        d = message_to_dict(original)
        restored = message_from_dict(d)
        assert isinstance(restored, SceneMessage)
        assert len(restored.elements) == 1
        modal = restored.elements[0]
        assert isinstance(modal, ModalElement)
        assert modal.title == "Confirm"
        assert len(modal.children) == 2

    def test_input_number_scene_roundtrip(self):
        original = SceneMessage(
            id="s1",
            elements=[
                InputNumberElement(id="in1", label="Price", value=9.99, step=0.01),
            ],
            frame_id="s1",
        )
        d = message_to_dict(original)
        restored = message_from_dict(d)
        assert isinstance(restored, SceneMessage)
        assert len(restored.elements) == 1
        assert isinstance(restored.elements[0], InputNumberElement)


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


# ---------------------------------------------------------------------------
# IntrospectRequest / IntrospectResponse
# ---------------------------------------------------------------------------


class TestIntrospect:
    def test_introspect_request_roundtrip(self):
        original = IntrospectRequest(scene_id="s1")
        d = message_to_dict(original)
        assert d["type"] == "introspect_request"
        assert d["scene_id"] == "s1"
        restored = message_from_dict(d)
        assert isinstance(restored, IntrospectRequest)
        assert restored.scene_id == "s1"

    def test_introspect_response_roundtrip(self):
        elements = [
            {"kind": "text", "id": "t1", "content": "hello"},
            {"kind": "button", "id": "b1", "label": "OK"},
        ]
        original = IntrospectResponse(scene_id="s1", elements=elements)
        d = message_to_dict(original)
        assert d["type"] == "introspect_response"
        assert d["scene_id"] == "s1"
        assert len(d["elements"]) == 2
        assert "error" not in d
        restored = message_from_dict(d)
        assert isinstance(restored, IntrospectResponse)
        assert restored.scene_id == "s1"
        assert restored.elements == elements
        assert restored.error is None

    def test_introspect_response_error_roundtrip(self):
        original = IntrospectResponse(
            scene_id="missing", error="Scene 'missing' not found"
        )
        d = message_to_dict(original)
        assert d["error"] == "Scene 'missing' not found"
        assert d["elements"] == []
        restored = message_from_dict(d)
        assert isinstance(restored, IntrospectResponse)
        assert restored.scene_id == "missing"
        assert restored.error == "Scene 'missing' not found"
        assert restored.elements == []


# ---------------------------------------------------------------------------
# ListScenesRequest / ListScenesResponse
# ---------------------------------------------------------------------------


class TestListScenes:
    def test_list_scenes_request_roundtrip(self) -> None:
        original = ListScenesRequest()
        d = message_to_dict(original)
        assert d["type"] == "list_scenes_request"
        restored = message_from_dict(d)
        assert isinstance(restored, ListScenesRequest)

    def test_list_scenes_response_roundtrip(self) -> None:
        scenes = [
            {"scene_id": "s1", "element_count": 3, "frame_id": "f1", "owner_fd": 5},
        ]
        frames = [
            {
                "frame_id": "f1",
                "title": "Main",
                "scene_count": 1,
                "scene_ids": ["s1"],
                "layout": "tab",
            },
        ]
        original = ListScenesResponse(scenes=scenes, frames=frames)
        d = message_to_dict(original)
        assert d["type"] == "list_scenes_response"
        assert len(d["scenes"]) == 1
        assert len(d["frames"]) == 1
        restored = message_from_dict(d)
        assert isinstance(restored, ListScenesResponse)
        assert restored.scenes == scenes
        assert restored.frames == frames

    def test_list_scenes_response_empty_roundtrip(self) -> None:
        original = ListScenesResponse()
        d = message_to_dict(original)
        assert d["scenes"] == []
        assert d["frames"] == []
        restored = message_from_dict(d)
        assert isinstance(restored, ListScenesResponse)
        assert restored.scenes == []
        assert restored.frames == []


# ---------------------------------------------------------------------------
# ScreenshotRequest / ScreenshotResponse
# ---------------------------------------------------------------------------


class TestScreenshot:
    def test_screenshot_request_roundtrip(self) -> None:
        original = ScreenshotRequest()
        d = message_to_dict(original)
        assert d["type"] == "screenshot_request"
        restored = message_from_dict(d)
        assert isinstance(restored, ScreenshotRequest)

    def test_screenshot_response_with_path_roundtrip(self) -> None:
        original = ScreenshotResponse(path="/tmp/lux-screenshot-abc.png")
        d = message_to_dict(original)
        assert d["type"] == "screenshot_response"
        assert d["path"] == "/tmp/lux-screenshot-abc.png"
        assert "error" not in d
        restored = message_from_dict(d)
        assert isinstance(restored, ScreenshotResponse)
        assert restored.path == "/tmp/lux-screenshot-abc.png"
        assert restored.error is None

    def test_screenshot_response_with_error_roundtrip(self) -> None:
        original = ScreenshotResponse(error="OpenGL not available")
        d = message_to_dict(original)
        assert d["type"] == "screenshot_response"
        assert d["path"] == ""
        assert d["error"] == "OpenGL not available"
        restored = message_from_dict(d)
        assert isinstance(restored, ScreenshotResponse)
        assert restored.path == ""
        assert restored.error == "OpenGL not available"

    def test_screenshot_response_defaults(self) -> None:
        resp = ScreenshotResponse()
        assert resp.path == ""
        assert resp.error is None
        assert resp.type == "screenshot_response"


# ---------------------------------------------------------------------------
# MessageRegistry
# ---------------------------------------------------------------------------


class TestMessageRegistry:
    """Tests for the MessageRegistry class introduced by the codec refactor."""

    def test_isolated_registry_roundtrip(self) -> None:
        """Create a fresh registry, register one type, round-trip it."""
        from punt_lux.protocol.messages import MessageRegistry

        def _ping_ser(m: PingMessage) -> dict[str, Any]:
            return {"type": "ping", "ts": m.ts}

        def _ping_de(d: dict[str, Any]) -> PingMessage:
            return PingMessage(ts=d.get("ts"))

        reg = MessageRegistry()
        reg.register("ping", PingMessage, _ping_ser, _ping_de)
        d = reg.to_dict(PingMessage(ts=1.0))
        restored = reg.from_dict(d)
        assert isinstance(restored, PingMessage)
        assert restored.ts == 1.0

    def test_duplicate_registration_raises(self) -> None:
        """Registering the same type string twice is a ValueError."""
        from punt_lux.protocol.messages import MessageRegistry

        def _ser(m: PingMessage) -> dict[str, Any]:
            return {}

        def _de(d: dict[str, Any]) -> PingMessage:
            return PingMessage()

        reg = MessageRegistry()
        reg.register("ping", PingMessage, _ser, _de)
        with pytest.raises(ValueError, match="Duplicate"):
            reg.register("ping", PingMessage, _ser, _de)

    def test_unknown_type_returns_unknown_message(self) -> None:
        """Unregistered type strings produce UnknownMessage."""
        from punt_lux.protocol.messages import MessageRegistry

        reg = MessageRegistry()
        msg = reg.from_dict({"type": "future_type", "x": 1})
        assert isinstance(msg, UnknownMessage)
        assert msg.raw_type == "future_type"

    def test_missing_type_field_raises(self) -> None:
        """Missing or invalid 'type' field raises ValueError."""
        from punt_lux.protocol.messages import MessageRegistry

        reg = MessageRegistry()
        with pytest.raises(ValueError, match="missing or invalid"):
            reg.from_dict({"data": 42})

    def test_unhashable_type_raises_valueerror(self) -> None:
        """Unhashable type values (list, dict) raise ValueError, not TypeError."""
        from punt_lux.protocol.messages import MessageRegistry

        reg = MessageRegistry()
        with pytest.raises(ValueError, match="missing or invalid"):
            reg.from_dict({"type": ["scene"]})
        with pytest.raises(ValueError, match="missing or invalid"):
            reg.from_dict({"type": {"nested": "dict"}})

    def test_registry_completeness(self) -> None:
        """Every non-unknown message type is registered on the default registry."""
        from punt_lux.protocol.messages import _registry

        expected_types = {
            "scene",
            "clear",
            "ping",
            "introspect_request",
            "introspect_response",
            "list_scenes_request",
            "list_scenes_response",
            "screenshot_request",
            "screenshot_response",
            "menu",
            "theme",
            "register_menu",
            "connect",
            "query_request",
            "query_response",
            "ready",
            "ack",
            "remote_invocation",
            "observer",
            "pong",
            "unknown",
        }
        assert _registry.registered_types == expected_types
