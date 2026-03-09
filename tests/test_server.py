"""Unit tests for punt_lux.server — MCP tool functions."""

from __future__ import annotations

import time
from typing import Any
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
    MarkdownElement,
    PlotElement,
    PongMessage,
    ProgressElement,
    RenderFunctionElement,
    SelectableElement,
    SliderElement,
    SpinnerElement,
    TabBarElement,
    TableElement,
    TreeElement,
    WindowElement,
    element_from_dict,
)
from punt_lux.server import (
    _layout_diagram,
    clear,
    ping,
    recv,
    set_menu,
    set_theme,
    show,
    show_dashboard,
    show_diagram,
    show_table,
    update,
)


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

    def test_plot_element(self) -> None:
        elem = element_from_dict(
            {
                "kind": "plot",
                "id": "p1",
                "title": "Trend",
                "x_label": "Time",
                "y_label": "Value",
                "series": [
                    {"label": "y", "type": "line", "x": [1, 2, 3], "y": [10, 20, 15]},
                ],
            }
        )
        assert isinstance(elem, PlotElement)
        assert elem.title == "Trend"
        assert elem.x_label == "Time"
        assert len(elem.series) == 1

    def test_plot_defaults(self) -> None:
        elem = element_from_dict({"kind": "plot", "id": "p1"})
        assert isinstance(elem, PlotElement)
        assert elem.title == ""
        assert elem.x_label == ""
        assert elem.y_label == ""
        assert elem.width == -1
        assert elem.height == 300
        assert elem.series == []

    def test_progress_element(self) -> None:
        elem = element_from_dict(
            {"kind": "progress", "id": "pg1", "fraction": 0.75, "label": "75%"}
        )
        assert isinstance(elem, ProgressElement)
        assert elem.fraction == 0.75
        assert elem.label == "75%"

    def test_progress_defaults(self) -> None:
        elem = element_from_dict({"kind": "progress", "id": "pg1"})
        assert isinstance(elem, ProgressElement)
        assert elem.fraction == 0.0
        assert elem.label == ""

    def test_spinner_element(self) -> None:
        elem = element_from_dict(
            {"kind": "spinner", "id": "sp1", "label": "Wait", "radius": 20.0}
        )
        assert isinstance(elem, SpinnerElement)
        assert elem.label == "Wait"
        assert elem.radius == 20.0

    def test_spinner_defaults(self) -> None:
        elem = element_from_dict({"kind": "spinner", "id": "sp1"})
        assert isinstance(elem, SpinnerElement)
        assert elem.radius == 16.0
        assert elem.color == "#3399FF"

    def test_markdown_element(self) -> None:
        elem = element_from_dict(
            {"kind": "markdown", "id": "md1", "content": "**bold**"}
        )
        assert isinstance(elem, MarkdownElement)
        assert elem.content == "**bold**"

    def test_markdown_defaults(self) -> None:
        elem = element_from_dict({"kind": "markdown", "id": "md1"})
        assert isinstance(elem, MarkdownElement)
        assert elem.content == ""

    def test_render_function_element(self) -> None:
        elem = element_from_dict(
            {
                "kind": "render_function",
                "id": "rf1",
                "source": "def render(ctx):\n    pass",
            }
        )
        assert isinstance(elem, RenderFunctionElement)
        assert elem.source == "def render(ctx):\n    pass"
        assert elem.id == "rf1"

    def test_render_function_element_defaults(self) -> None:
        elem = element_from_dict(
            {"kind": "render_function", "id": "rf1", "source": "def render(ctx): pass"}
        )
        assert isinstance(elem, RenderFunctionElement)
        assert elem.kind == "render_function"
        assert elem.tooltip is None

    def test_tooltip_from_dict(self) -> None:
        elem = element_from_dict(
            {"kind": "text", "id": "t1", "content": "hi", "tooltip": "help"}
        )
        assert elem.tooltip == "help"

    def test_tooltip_default_none(self) -> None:
        elem = element_from_dict({"kind": "text", "id": "t1", "content": "hi"})
        assert elem.tooltip is None

    def test_unknown_kind_raises(self) -> None:
        import pytest

        with pytest.raises(ValueError, match="Unknown element kind"):
            element_from_dict({"kind": "bogus", "id": "x"})


def _mock_client() -> MagicMock:
    client = MagicMock()
    client.is_connected = True
    return client


class TestSetMenuTool:
    @patch("punt_lux.server._get_client")
    def test_set_menu_returns_ok(self, mock_get: MagicMock) -> None:
        client = _mock_client()
        mock_get.return_value = client

        menus = [{"label": "Tools", "items": [{"label": "Run", "id": "run"}]}]
        result = set_menu(menus)
        assert result == "ok"
        client.set_menu.assert_called_once_with(menus)


class TestSetThemeTool:
    @patch("punt_lux.server._get_client")
    def test_set_theme_returns_theme_name(self, mock_get: MagicMock) -> None:
        client = _mock_client()
        mock_get.return_value = client

        result = set_theme("imgui_colors_light")
        assert result == "theme:imgui_colors_light"
        client.set_theme.assert_called_once_with("imgui_colors_light")


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


class TestShowTableTool:
    @patch("punt_lux.server._get_client")
    def test_show_table_minimal(self, mock_get: MagicMock) -> None:
        client = _mock_client()
        client.show.return_value = AckMessage(scene_id="t1", ts=time.time())
        mock_get.return_value = client

        result = show_table(
            "t1",
            columns=["Name", "Score"],
            rows=[["Alice", 95], ["Bob", 87]],
        )
        assert result == "ack:t1"
        client.show.assert_called_once()
        elements = client.show.call_args[0][1]
        assert len(elements) == 1
        assert isinstance(elements[0], TableElement)
        assert elements[0].columns == ["Name", "Score"]
        assert elements[0].flags == ["borders", "row_bg"]

    @patch("punt_lux.server._get_client")
    def test_show_table_with_filters_and_detail(self, mock_get: MagicMock) -> None:
        client = _mock_client()
        client.show.return_value = AckMessage(scene_id="t2", ts=time.time())
        mock_get.return_value = client

        result = show_table(
            "t2",
            columns=["ID", "Title", "Status"],
            rows=[["1", "Fix bug", "Open"]],
            filters=[
                {"type": "search", "column": [0, 1], "hint": "Search..."},
                {"type": "combo", "column": 2, "items": ["All", "Open"]},
            ],
            detail={
                "fields": ["ID", "Status"],
                "rows": [["1", "Open"]],
                "body": ["A bug that needs fixing."],
            },
            title="Issues",
        )
        assert result == "ack:t2"
        elements = client.show.call_args[0][1]
        table = elements[0]
        assert isinstance(table, TableElement)
        assert table.filters is not None
        assert len(table.filters) == 2
        assert table.detail is not None
        assert table.detail.fields == ["ID", "Status"]

    @patch("punt_lux.server._get_client")
    def test_show_table_custom_flags(self, mock_get: MagicMock) -> None:
        client = _mock_client()
        client.show.return_value = AckMessage(scene_id="t3", ts=time.time())
        mock_get.return_value = client

        show_table(
            "t3",
            columns=["A"],
            rows=[["x"]],
            flags=["borders", "resizable"],
        )
        elements = client.show.call_args[0][1]
        assert elements[0].flags == ["borders", "resizable"]


class TestShowDashboardTool:
    @patch("punt_lux.server._get_client")
    def test_dashboard_metrics_only(self, mock_get: MagicMock) -> None:
        client = _mock_client()
        client.show.return_value = AckMessage(scene_id="d1", ts=time.time())
        mock_get.return_value = client

        result = show_dashboard(
            "d1",
            metrics=[
                {"label": "Users", "value": "100"},
                {"label": "Revenue", "value": "$5k"},
            ],
        )
        assert result == "ack:d1"
        elements = client.show.call_args[0][1]
        # metrics group only (no trailing separator for single section)
        assert len(elements) == 1
        assert elements[0].kind == "group"
        assert len(elements[0].children) == 2

    @patch("punt_lux.server._get_client")
    def test_dashboard_all_sections(self, mock_get: MagicMock) -> None:
        client = _mock_client()
        client.show.return_value = AckMessage(scene_id="d2", ts=time.time())
        mock_get.return_value = client

        show_dashboard(
            "d2",
            metrics=[{"label": "Total", "value": "42"}],
            charts=[
                {
                    "id": "c1",
                    "title": "Trend",
                    "series": [{"label": "y", "type": "line", "x": [1], "y": [1]}],
                }
            ],
            table_columns=["Name", "Value"],
            table_rows=[["test", "pass"]],
            title="Dashboard",
        )
        elements = client.show.call_args[0][1]
        kinds = [e.kind for e in elements]
        assert "group" in kinds  # metrics
        assert "plot" in kinds  # chart
        assert "table" in kinds  # table
        assert kinds.count("separator") == 2

    @patch("punt_lux.server._get_client")
    def test_dashboard_empty(self, mock_get: MagicMock) -> None:
        client = _mock_client()
        client.show.return_value = AckMessage(scene_id="d3", ts=time.time())
        mock_get.return_value = client

        show_dashboard("d3")
        elements = client.show.call_args[0][1]
        assert elements == []


class TestShowDiagramLayout:
    """Tests for the diagram layout engine (no display needed)."""

    def test_minimal_diagram(self) -> None:
        layers = [
            {
                "label": "L1",
                "nodes": [
                    {"id": "a", "label": "Node A"},
                    {"id": "b", "label": "Node B"},
                ],
            },
        ]
        w, h, cmds = _layout_diagram(layers, None)
        assert w > 0
        assert h > 0
        rects = [c for c in cmds if c["cmd"] == "rect"]
        texts = [c for c in cmds if c["cmd"] == "text"]
        # 2 nodes * 2 rects each (fill + border) = 4
        assert len(rects) == 4
        # 2 node labels + 1 layer label = 3
        assert len(texts) == 3

    def test_multi_layer_with_edges(self) -> None:
        layers = [
            {
                "label": "Top",
                "nodes": [
                    {"id": "a", "label": "A"},
                    {"id": "b", "label": "B"},
                ],
            },
            {
                "label": "Mid",
                "nodes": [
                    {"id": "c", "label": "C"},
                ],
            },
            {
                "label": "Bot",
                "nodes": [
                    {"id": "d", "label": "D"},
                    {"id": "e", "label": "E"},
                ],
            },
        ]
        edges = [
            {"from": "a", "to": "c", "label": "uses"},
            {"from": "b", "to": "c"},
            {"from": "c", "to": "d"},
            {"from": "c", "to": "e"},
        ]
        _w, _h, cmds = _layout_diagram(layers, edges)
        lines = [c for c in cmds if c["cmd"] == "line"]
        triangles = [c for c in cmds if c["cmd"] == "triangle"]
        # 4 edges = 4 lines + 4 arrowheads
        assert len(lines) == 4
        assert len(triangles) == 4
        # edge label "uses" should appear once
        edge_labels = [c for c in cmds if c["cmd"] == "text" and c["text"] == "uses"]
        assert len(edge_labels) == 1

    def test_no_edges(self) -> None:
        layers = [
            {"label": "Only", "nodes": [{"id": "x", "label": "X"}]},
        ]
        _w, _h, cmds = _layout_diagram(layers, None)
        lines = [c for c in cmds if c["cmd"] == "line"]
        assert len(lines) == 0

    def test_empty_layer_skipped(self) -> None:
        layers: list[dict[str, Any]] = [
            {"label": "Has nodes", "nodes": [{"id": "a", "label": "A"}]},
            {"label": "Empty", "nodes": []},
            {"label": "Also has", "nodes": [{"id": "b", "label": "B"}]},
        ]
        _w, _h, cmds = _layout_diagram(layers, None)
        rects = [c for c in cmds if c["cmd"] == "rect"]
        # 2 nodes * 2 rects = 4
        assert len(rects) == 4

    def test_long_labels_widen_boxes(self) -> None:
        short = [{"label": "S", "nodes": [{"id": "s", "label": "Hi"}]}]
        long = [
            {
                "label": "L",
                "nodes": [
                    {"id": "l", "label": "A very long node label here"},
                ],
            }
        ]
        _w1, _h1, cmds1 = _layout_diagram(short, None)
        _w2, _h2, cmds2 = _layout_diagram(long, None)
        # extract rect widths
        r1 = next(c for c in cmds1 if c["cmd"] == "rect")
        r2 = next(c for c in cmds2 if c["cmd"] == "rect")
        w1 = r1["max"][0] - r1["min"][0]
        w2 = r2["max"][0] - r2["min"][0]
        assert w2 > w1

    def test_detail_adds_height(self) -> None:
        no_detail = [
            {
                "label": "L",
                "nodes": [
                    {"id": "a", "label": "A"},
                ],
            }
        ]
        with_detail = [
            {
                "label": "L",
                "nodes": [
                    {"id": "a", "label": "A", "detail": "subtitle"},
                ],
            }
        ]
        _w1, h1, _cmds1 = _layout_diagram(no_detail, None)
        _w2, h2, _cmds2 = _layout_diagram(with_detail, None)
        assert h2 > h1


class TestShowDiagramTool:
    @patch("punt_lux.server._get_client")
    def test_show_diagram_returns_ack(self, mock_get: MagicMock) -> None:
        client = _mock_client()
        client.show.return_value = AckMessage(scene_id="arch", ts=time.time())
        mock_get.return_value = client

        result = show_diagram(
            "arch",
            layers=[
                {"label": "Top", "nodes": [{"id": "a", "label": "A"}]},
                {"label": "Bot", "nodes": [{"id": "b", "label": "B"}]},
            ],
            edges=[{"from": "a", "to": "b"}],
            title="Test Diagram",
        )
        assert result == "ack:arch"

        # verify show() was called with a draw element
        elements = client.show.call_args[0][1]
        assert len(elements) == 1
        assert isinstance(elements[0], DrawElement)
        assert elements[0].width > 0
        assert elements[0].height > 0
        assert len(elements[0].commands) > 0


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
