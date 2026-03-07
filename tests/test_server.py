"""Unit tests for punt_lux.server — MCP tool functions."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

from punt_lux.protocol import (
    AckMessage,
    CheckboxElement,
    CollapsingHeaderElement,
    ColorPickerElement,
    ComboElement,
    DrawElement,
    GroupElement,
    InputTextElement,
    InteractionMessage,
    PongMessage,
    SelectableElement,
    SliderElement,
    TabBarElement,
    TableElement,
    TreeElement,
    WindowElement,
    element_from_dict,
)
from punt_lux.server import clear, ping, recv, show, update


class TestElementFromDict:
    def test_text_element(self) -> None:
        elem = element_from_dict(
            {"kind": "text", "id": "t1", "content": "Hello", "style": "heading"}
        )
        assert elem.kind == "text"
        assert elem.id == "t1"

    def test_button_element(self) -> None:
        elem = element_from_dict({"kind": "button", "id": "b1", "label": "Click"})
        assert elem.kind == "button"

    def test_image_element(self) -> None:
        elem = element_from_dict({"kind": "image", "id": "i1", "path": "/img.png"})
        assert elem.kind == "image"

    def test_separator_element(self) -> None:
        elem = element_from_dict({"kind": "separator"})
        assert elem.kind == "separator"

    def test_default_kind_is_text(self) -> None:
        elem = element_from_dict({"id": "t1", "content": "Hi"})
        assert elem.kind == "text"

    def test_text_defaults_content_to_empty(self) -> None:
        elem = element_from_dict({"kind": "text", "id": "t1"})
        assert elem.content == ""  # type: ignore[union-attr]

    def test_button_defaults_label_to_empty(self) -> None:
        elem = element_from_dict({"kind": "button", "id": "b1"})
        assert elem.label == ""  # type: ignore[union-attr]

    def test_slider_element(self) -> None:
        elem = element_from_dict(
            {"kind": "slider", "id": "sl1", "label": "Vol", "value": 50.0}
        )
        assert elem.kind == "slider"
        assert elem.id == "sl1"

    def test_slider_defaults(self) -> None:
        elem = element_from_dict({"kind": "slider", "id": "sl1"})
        assert isinstance(elem, SliderElement)
        assert elem.label == ""
        assert elem.value == 0.0

    def test_checkbox_element(self) -> None:
        elem = element_from_dict(
            {"kind": "checkbox", "id": "cb1", "label": "On", "value": True}
        )
        assert isinstance(elem, CheckboxElement)
        assert elem.value is True

    def test_combo_element(self) -> None:
        elem = element_from_dict(
            {"kind": "combo", "id": "co1", "label": "Pick", "items": ["A", "B"]}
        )
        assert isinstance(elem, ComboElement)
        assert elem.items == ["A", "B"]

    def test_input_text_element(self) -> None:
        elem = element_from_dict(
            {"kind": "input_text", "id": "it1", "label": "Name", "hint": "who?"}
        )
        assert isinstance(elem, InputTextElement)
        assert elem.hint == "who?"

    def test_radio_element(self) -> None:
        elem = element_from_dict(
            {"kind": "radio", "id": "r1", "label": "Opt", "items": ["X", "Y"]}
        )
        assert elem.kind == "radio"

    def test_color_picker_element(self) -> None:
        elem = element_from_dict(
            {"kind": "color_picker", "id": "cp1", "label": "Bg", "value": "#FF0000"}
        )
        assert isinstance(elem, ColorPickerElement)
        assert elem.value == "#FF0000"

    def test_draw_element(self) -> None:
        elem = element_from_dict(
            {
                "kind": "draw",
                "id": "d1",
                "width": 200,
                "commands": [{"cmd": "line", "p1": [0, 0], "p2": [10, 10]}],
            }
        )
        assert isinstance(elem, DrawElement)
        assert elem.width == 200
        assert len(elem.commands) == 1

    def test_draw_element_defaults(self) -> None:
        elem = element_from_dict({"kind": "draw", "id": "d1"})
        assert isinstance(elem, DrawElement)
        assert elem.width == 400
        assert elem.height == 300
        assert elem.commands == []

    def test_group_element(self) -> None:
        elem = element_from_dict(
            {
                "kind": "group",
                "id": "g1",
                "layout": "columns",
                "children": [{"kind": "text", "id": "t1", "content": "Hi"}],
            }
        )
        assert isinstance(elem, GroupElement)
        assert elem.layout == "columns"
        assert len(elem.children) == 1

    def test_group_defaults(self) -> None:
        elem = element_from_dict({"kind": "group", "id": "g1"})
        assert isinstance(elem, GroupElement)
        assert elem.layout == "rows"
        assert elem.children == []

    def test_tab_bar_element(self) -> None:
        elem = element_from_dict(
            {
                "kind": "tab_bar",
                "id": "tb1",
                "tabs": [
                    {
                        "label": "A",
                        "children": [{"kind": "text", "id": "t1", "content": "In A"}],
                    },
                ],
            }
        )
        assert isinstance(elem, TabBarElement)
        assert len(elem.tabs) == 1
        assert elem.tabs[0]["label"] == "A"

    def test_collapsing_header_element(self) -> None:
        elem = element_from_dict(
            {
                "kind": "collapsing_header",
                "id": "ch1",
                "label": "Details",
                "default_open": True,
                "children": [{"kind": "button", "id": "b1", "label": "Go"}],
            }
        )
        assert isinstance(elem, CollapsingHeaderElement)
        assert elem.label == "Details"
        assert elem.default_open is True
        assert len(elem.children) == 1

    def test_window_element(self) -> None:
        elem = element_from_dict(
            {
                "kind": "window",
                "id": "w1",
                "title": "Panel",
                "x": 100,
                "y": 50,
                "children": [{"kind": "text", "id": "t1", "content": "Hi"}],
            }
        )
        assert isinstance(elem, WindowElement)
        assert elem.title == "Panel"
        assert elem.x == 100
        assert len(elem.children) == 1

    def test_window_defaults(self) -> None:
        elem = element_from_dict({"kind": "window", "id": "w1"})
        assert isinstance(elem, WindowElement)
        assert elem.title == ""
        assert elem.width == 300.0
        assert elem.no_move is False
        assert elem.children == []

    def test_selectable_element(self) -> None:
        elem = element_from_dict(
            {"kind": "selectable", "id": "s1", "label": "Item", "selected": True}
        )
        assert isinstance(elem, SelectableElement)
        assert elem.label == "Item"
        assert elem.selected is True

    def test_selectable_defaults(self) -> None:
        elem = element_from_dict({"kind": "selectable", "id": "s1"})
        assert isinstance(elem, SelectableElement)
        assert elem.label == ""
        assert elem.selected is False

    def test_tree_element(self) -> None:
        elem = element_from_dict(
            {
                "kind": "tree",
                "id": "tr1",
                "label": "Files",
                "nodes": [
                    {"label": "src", "children": [{"label": "main.py"}]},
                ],
            }
        )
        assert isinstance(elem, TreeElement)
        assert elem.label == "Files"
        assert len(elem.nodes) == 1

    def test_tree_defaults(self) -> None:
        elem = element_from_dict({"kind": "tree", "id": "tr1"})
        assert isinstance(elem, TreeElement)
        assert elem.label == ""
        assert elem.nodes == []

    def test_table_element(self) -> None:
        elem = element_from_dict(
            {
                "kind": "table",
                "id": "tbl1",
                "columns": ["Name", "Score"],
                "rows": [["Alice", 95], ["Bob", 87]],
                "flags": ["borders", "row_bg", "resizable"],
            }
        )
        assert isinstance(elem, TableElement)
        assert elem.columns == ["Name", "Score"]
        assert len(elem.rows) == 2
        assert "resizable" in elem.flags

    def test_table_defaults(self) -> None:
        elem = element_from_dict({"kind": "table", "id": "tbl1"})
        assert isinstance(elem, TableElement)
        assert elem.columns == []
        assert elem.rows == []
        assert elem.flags == ["borders", "row_bg"]

    def test_unknown_kind_raises(self) -> None:
        import pytest

        with pytest.raises(ValueError, match="Unknown element kind"):
            element_from_dict({"kind": "bogus", "id": "x"})


def _mock_client() -> MagicMock:
    client = MagicMock()
    client.is_connected = True
    return client


class TestShowTool:
    @patch("punt_lux.server._get_client")
    def test_show_returns_ack(self, mock_get: MagicMock) -> None:
        client = _mock_client()
        client.show.return_value = AckMessage(scene_id="s1", ts=time.time())
        mock_get.return_value = client

        result = show("s1", [{"kind": "text", "id": "t1", "content": "Hi"}])
        assert result == "ack:s1"
        client.show.assert_called_once()

    @patch("punt_lux.server._get_client")
    def test_show_timeout(self, mock_get: MagicMock) -> None:
        client = _mock_client()
        client.show.return_value = None
        mock_get.return_value = client

        result = show("s1", [{"kind": "text", "id": "t1", "content": "Hi"}])
        assert result == "timeout"


class TestUpdateTool:
    @patch("punt_lux.server._get_client")
    def test_update_returns_ack(self, mock_get: MagicMock) -> None:
        client = _mock_client()
        client.update.return_value = AckMessage(scene_id="s1", ts=time.time())
        mock_get.return_value = client

        result = update("s1", [{"id": "t1", "set": {"content": "New"}}])
        assert result == "ack:s1"

    @patch("punt_lux.server._get_client")
    def test_update_timeout(self, mock_get: MagicMock) -> None:
        client = _mock_client()
        client.update.return_value = None
        mock_get.return_value = client

        result = update("s1", [{"id": "t1", "set": {"content": "New"}}])
        assert result == "timeout"


class TestClearTool:
    @patch("punt_lux.server._get_client")
    def test_clear_returns_cleared(self, mock_get: MagicMock) -> None:
        client = _mock_client()
        mock_get.return_value = client

        result = clear()
        assert result == "cleared"
        client.clear.assert_called_once()


class TestPingTool:
    @patch("punt_lux.server.time")
    @patch("punt_lux.server._get_client")
    def test_ping_returns_rtt(self, mock_get: MagicMock, mock_time: MagicMock) -> None:
        client = _mock_client()
        ts = 1000.0
        mock_time.time.return_value = ts + 0.042
        client.ping.return_value = PongMessage(ts=ts, display_ts=ts + 0.005)
        mock_get.return_value = client

        result = ping()
        assert result == "pong:rtt=0.042s"

    @patch("punt_lux.server._get_client")
    def test_ping_timeout(self, mock_get: MagicMock) -> None:
        client = _mock_client()
        client.ping.return_value = None
        mock_get.return_value = client

        result = ping()
        assert result == "timeout"


class TestRecvTool:
    @patch("punt_lux.server._get_client")
    def test_recv_interaction(self, mock_get: MagicMock) -> None:
        client = _mock_client()
        client.recv.return_value = InteractionMessage(
            element_id="b1", action="click", ts=time.time(), value=True
        )
        mock_get.return_value = client

        result = recv(timeout=1.0)
        assert "interaction" in result
        assert "b1" in result
        assert "click" in result

    @patch("punt_lux.server._get_client")
    def test_recv_none(self, mock_get: MagicMock) -> None:
        client = _mock_client()
        client.recv.return_value = None
        mock_get.return_value = client

        result = recv(timeout=0.1)
        assert result == "none"
