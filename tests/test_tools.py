"""Unit tests for punt_lux.tools — MCP tool functions."""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from punt_lux.paths import DisplayPaths
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
    QueryResponse,
    SelectableElement,
    SliderElement,
    SpinnerElement,
    TabBarElement,
    TableElement,
    TreeElement,
    WindowElement,
    element_from_dict,
)
from punt_lux.tools import (
    clear,
    display_mode,
    inspect_scene,
    list_scenes,
    ping,
    recv,
    register_tool,
    screenshot,
    set_display_mode,
    set_menu,
    set_theme,
    show,
    show_dashboard,
    show_table,
    update,
)
from punt_lux.tools.server import (
    _cleanup_session,
    _session_key,
    _session_menus,
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

    def test_missing_kind_raises(self) -> None:
        with pytest.raises(ValueError, match="kind"):
            element_from_dict({"id": "t1", "content": "Hi"})

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
        assert elem.commands == ()

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

    def test_tooltip_from_dict(self) -> None:
        elem = element_from_dict(
            {"kind": "text", "id": "t1", "content": "hi", "tooltip": "help"}
        )
        assert elem.tooltip == "help"

    def test_tooltip_default_none(self) -> None:
        elem = element_from_dict({"kind": "text", "id": "t1", "content": "hi"})
        assert elem.tooltip is None

    def test_unknown_kind_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown element kind"):
            element_from_dict({"kind": "bogus", "id": "x"})


def _mock_client() -> MagicMock:
    client = MagicMock()
    client.is_connected = True
    return client


class TestSetMenuTool:
    @patch("punt_lux.tools.tools._get_client")
    def test_set_menu_returns_ok(self, mock_get: MagicMock) -> None:
        client = _mock_client()
        mock_get.return_value = client

        menus = [{"label": "Tools", "items": [{"label": "Run", "id": "run"}]}]
        result = set_menu(menus)
        assert result == "ok"
        client.set_menu.assert_called_once_with(menus)


class TestSetThemeTool:
    @patch.object(DisplayPaths, "is_running", return_value=True)
    @patch("punt_lux.tools.tools._get_client")
    def test_set_theme_returns_theme_name(
        self, mock_get: MagicMock, _mock_running: MagicMock
    ) -> None:
        client = _mock_client()
        mock_response = MagicMock()
        mock_response.error = None
        mock_response.result = {"theme": "imgui_colors_light"}
        client.query.return_value = mock_response
        mock_get.return_value = client

        result = set_theme("imgui_colors_light")
        assert result == "theme:imgui_colors_light"
        client.query.assert_called_once_with(
            "set_theme", {"theme": "imgui_colors_light"}
        )


class TestShowTool:
    @patch("punt_lux.tools.tools._get_client")
    def test_show_returns_ack(self, mock_get: MagicMock) -> None:
        client = _mock_client()
        client.show.return_value = AckMessage(scene_id="s1", ts=time.time())
        mock_get.return_value = client

        result = show("s1", [{"kind": "text", "id": "t1", "content": "Hi"}])
        assert result == "ack:s1"
        client.show.assert_called_once()

    @patch("punt_lux.tools.tools._get_client")
    def test_show_timeout(self, mock_get: MagicMock) -> None:
        client = _mock_client()
        client.show.return_value = None
        mock_get.return_value = client

        result = show("s1", [{"kind": "text", "id": "t1", "content": "Hi"}])
        assert result == "timeout"


class TestShowTableTool:
    @patch("punt_lux.tools.tools._get_client")
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

    @patch("punt_lux.tools.tools._get_client")
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

    @patch("punt_lux.tools.tools._get_client")
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
    @patch("punt_lux.tools.tools._get_client")
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

    @patch("punt_lux.tools.tools._get_client")
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

    @patch("punt_lux.tools.tools._get_client")
    def test_dashboard_empty(self, mock_get: MagicMock) -> None:
        client = _mock_client()
        client.show.return_value = AckMessage(scene_id="d3", ts=time.time())
        mock_get.return_value = client

        show_dashboard("d3")
        elements = client.show.call_args[0][1]
        assert elements == []


class TestUpdateTool:
    @patch("punt_lux.tools.tools._get_client")
    def test_update_returns_ack(self, mock_get: MagicMock) -> None:
        client = _mock_client()
        client.update.return_value = AckMessage(scene_id="s1", ts=time.time())
        mock_get.return_value = client

        result = update("s1", [{"id": "t1", "set": {"content": "New"}}])
        assert result == "ack:s1"

    @patch("punt_lux.tools.tools._get_client")
    def test_update_timeout(self, mock_get: MagicMock) -> None:
        client = _mock_client()
        client.update.return_value = None
        mock_get.return_value = client

        result = update("s1", [{"id": "t1", "set": {"content": "New"}}])
        assert result == "timeout"


class TestClearTool:
    @patch("punt_lux.tools.tools._get_client")
    @patch.object(DisplayPaths, "is_running", return_value=True)
    def test_clear_returns_cleared(
        self, mock_running: MagicMock, mock_get: MagicMock
    ) -> None:
        client = _mock_client()
        mock_get.return_value = client

        result = clear()
        assert result == "cleared"
        client.clear.assert_called_once()


class TestPingTool:
    @patch("punt_lux.tools.tools.time")
    @patch("punt_lux.tools.tools._get_client")
    @patch.object(DisplayPaths, "is_running", return_value=True)
    def test_ping_returns_rtt(
        self,
        mock_running: MagicMock,
        mock_get: MagicMock,
        mock_time: MagicMock,
    ) -> None:
        client = _mock_client()
        ts = 1000.0
        mock_time.time.return_value = ts + 0.042
        client.ping.return_value = PongMessage(ts=ts, display_ts=ts + 0.005)
        mock_get.return_value = client

        result = ping()
        assert result == "pong rtt=0.042s"

    @patch("punt_lux.tools.tools._get_client")
    @patch.object(DisplayPaths, "is_running", return_value=True)
    def test_ping_timeout(self, mock_running: MagicMock, mock_get: MagicMock) -> None:
        client = _mock_client()
        client.ping.return_value = None
        mock_get.return_value = client

        result = ping()
        assert result == "timeout"


class TestRecvTool:
    @patch("punt_lux.tools.tools._get_client")
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

    @patch("punt_lux.tools.tools._get_client")
    def test_recv_none(self, mock_get: MagicMock) -> None:
        client = _mock_client()
        client.recv.return_value = None
        mock_get.return_value = client

        result = recv(timeout=0.1)
        assert result == "none"


def _mock_config_manager_cls(
    cfg: MagicMock | None = None,
) -> MagicMock:
    """Build a mock ConfigManager class whose instances delegate to *cfg*."""
    mgr = MagicMock()
    if cfg is not None:
        mgr.read.return_value = cfg
    return MagicMock(return_value=mgr)


class TestDisplayModeTool:
    def test_display_mode_returns_on(self) -> None:
        cfg = MagicMock()
        cfg.display = "y"
        mock_cls = _mock_config_manager_cls(cfg)
        with patch("punt_lux.tools.tools.ConfigManager", mock_cls):
            result = display_mode()
        assert result == "display:on"

    def test_display_mode_returns_off(self) -> None:
        cfg = MagicMock()
        cfg.display = "n"
        mock_cls = _mock_config_manager_cls(cfg)
        with patch("punt_lux.tools.tools.ConfigManager", mock_cls):
            result = display_mode()
        assert result == "display:off"


class TestSetDisplayModeTool:
    @patch("punt_lux.tools.tools._get_client")
    def test_set_display_mode_y(self, mock_get: MagicMock) -> None:
        mock_get.return_value = _mock_client()
        mock_cls = _mock_config_manager_cls()
        with patch("punt_lux.tools.tools.ConfigManager", mock_cls):
            result = set_display_mode("y")
        assert result == "display:on"
        mock_cls.return_value.write_field.assert_called_once_with("display", "y")

    def test_set_display_mode_n(self) -> None:
        mock_cls = _mock_config_manager_cls()
        with patch("punt_lux.tools.tools.ConfigManager", mock_cls):
            result = set_display_mode("n")
        assert result == "display:off"
        mock_cls.return_value.write_field.assert_called_once_with("display", "n")

    def test_set_display_mode_invalid(self) -> None:
        with pytest.raises(ValueError, match="Invalid mode"):
            set_display_mode("bogus")


class TestDisplayModeRepoArg:
    """Regression for lux-r929 — config resolves to the caller's repo."""

    def test_set_then_read_roundtrip_in_repo(self, tmp_path: Path) -> None:
        """set_display_mode(repo=X) writes to X/.punt-labs/lux.md;
        display_mode(repo=X) reads it back. No MCP server cwd in the loop."""
        with patch("punt_lux.tools.tools._get_client", return_value=_mock_client()):
            assert set_display_mode("y", repo=str(tmp_path)) == "display:on"
        assert (tmp_path / ".punt-labs" / "lux.md").exists()
        assert display_mode(repo=str(tmp_path)) == "display:on"

        with patch("punt_lux.tools.tools._get_client", return_value=_mock_client()):
            assert set_display_mode("n", repo=str(tmp_path)) == "display:off"
        assert display_mode(repo=str(tmp_path)) == "display:off"

    def test_repo_paths_are_isolated(self, tmp_path: Path) -> None:
        """Two different repo paths maintain independent display-mode state."""
        repo_a = tmp_path / "a"
        repo_b = tmp_path / "b"
        repo_a.mkdir()
        repo_b.mkdir()
        with patch("punt_lux.tools.tools._get_client", return_value=_mock_client()):
            set_display_mode("y", repo=str(repo_a))
        set_display_mode("n", repo=str(repo_b))
        assert display_mode(repo=str(repo_a)) == "display:on"
        assert display_mode(repo=str(repo_b)) == "display:off"

    def test_repo_must_be_absolute(self) -> None:
        with pytest.raises(ValueError, match="absolute path"):
            display_mode(repo="relative/path")

    def test_repo_must_exist(self, tmp_path: Path) -> None:
        missing = tmp_path / "does-not-exist"
        with pytest.raises(ValueError, match="does not exist"):
            display_mode(repo=str(missing))

    def test_repo_none_falls_back_to_process_cwd(self) -> None:
        """When repo is omitted, behavior is the historical process-cwd path
        (the lux-r929 bug surface). Hooks and CLI rely on this fallback."""
        cfg = MagicMock()
        cfg.display = "y"
        mock_cls = _mock_config_manager_cls(cfg)
        with patch("punt_lux.tools.tools.ConfigManager", mock_cls):
            assert display_mode() == "display:on"
        # No config_path kwarg means the process-cwd resolver runs.
        mock_cls.assert_called_once_with()


class TestClearNoAutoSpawn:
    @patch("punt_lux.tools.tools._get_client")
    @patch.object(DisplayPaths, "is_running", return_value=False)
    def test_clear_noop_when_not_running(
        self, mock_running: MagicMock, mock_get: MagicMock
    ) -> None:

        result = clear()
        assert result == "cleared"
        mock_get.assert_not_called()

    @patch("punt_lux.tools.tools._get_client")
    @patch.object(DisplayPaths, "is_running", return_value=True)
    def test_clear_calls_client_when_running(
        self, mock_running: MagicMock, mock_get: MagicMock
    ) -> None:
        client = _mock_client()
        mock_get.return_value = client

        result = clear()
        assert result == "cleared"
        client.clear.assert_called_once()


class TestPingNoAutoSpawn:
    @patch("punt_lux.tools.tools._get_client")
    @patch.object(DisplayPaths, "is_running", return_value=False)
    def test_ping_not_running(
        self, mock_running: MagicMock, mock_get: MagicMock
    ) -> None:

        result = ping()
        assert result == "not running"
        mock_get.assert_not_called()

    @patch("punt_lux.tools.tools.time")
    @patch("punt_lux.tools.tools._get_client")
    @patch.object(DisplayPaths, "is_running", return_value=True)
    def test_ping_returns_rtt_when_running(
        self,
        mock_running: MagicMock,
        mock_get: MagicMock,
        mock_time: MagicMock,
    ) -> None:
        client = _mock_client()
        ts = 1000.0
        mock_time.time.return_value = ts + 0.042
        client.ping.return_value = PongMessage(ts=ts, display_ts=ts + 0.005)
        mock_get.return_value = client

        result = ping()
        assert result == "pong rtt=0.042s"


class TestInspectSceneTool:
    @patch("punt_lux.tools.tools._get_client")
    @patch.object(DisplayPaths, "is_running", return_value=False)
    def test_inspect_scene_not_running(
        self, mock_running: MagicMock, mock_get: MagicMock
    ) -> None:

        result = inspect_scene("s1")
        assert result == "not running"
        mock_get.assert_not_called()

    @patch("punt_lux.tools.tools._get_client")
    @patch.object(DisplayPaths, "is_running", return_value=True)
    def test_inspect_scene_returns_elements(
        self, mock_running: MagicMock, mock_get: MagicMock
    ) -> None:
        client = _mock_client()
        elements = [
            {"kind": "text", "id": "t1", "content": "hello"},
        ]
        client.query.return_value = QueryResponse(
            method="inspect_scene",
            result={"scene_id": "s1", "elements": elements},
        )
        mock_get.return_value = client

        result = inspect_scene("s1")
        assert '"scene_id": "s1"' in result
        assert '"content": "hello"' in result

    @patch("punt_lux.tools.tools._get_client")
    @patch.object(DisplayPaths, "is_running", return_value=True)
    def test_inspect_scene_not_found(
        self, mock_running: MagicMock, mock_get: MagicMock
    ) -> None:
        client = _mock_client()
        client.query.return_value = QueryResponse(
            method="inspect_scene",
            error="Scene 'missing' not found",
        )
        mock_get.return_value = client

        result = inspect_scene("missing")
        assert result == "error: Scene 'missing' not found"

    @patch("punt_lux.tools.tools._get_client")
    @patch.object(DisplayPaths, "is_running", return_value=True)
    def test_inspect_scene_timeout(
        self, mock_running: MagicMock, mock_get: MagicMock
    ) -> None:
        client = _mock_client()
        client.query.return_value = None
        mock_get.return_value = client

        result = inspect_scene("s1")
        assert result == "timeout"


class TestListScenesTool:
    @patch("punt_lux.tools.tools._get_client")
    @patch.object(DisplayPaths, "is_running", return_value=False)
    def test_list_scenes_not_running(
        self, mock_running: MagicMock, mock_get: MagicMock
    ) -> None:

        result = list_scenes()
        assert result == "not running"
        mock_get.assert_not_called()

    @patch("punt_lux.tools.tools._get_client")
    @patch.object(DisplayPaths, "is_running", return_value=True)
    def test_list_scenes_returns_data(
        self, mock_running: MagicMock, mock_get: MagicMock
    ) -> None:
        client = _mock_client()
        scenes = [
            {"scene_id": "s1", "element_count": 3, "frame_id": "f1", "owner_fd": 5},
        ]
        frames = [
            {"frame_id": "f1", "title": "Main", "scene_count": 1, "scene_ids": ["s1"]},
        ]
        client.query.return_value = QueryResponse(
            method="list_scenes",
            result={"scenes": scenes, "frames": frames},
        )
        mock_get.return_value = client

        result = list_scenes()
        assert '"scene_id": "s1"' in result
        assert '"frame_id": "f1"' in result

    @patch("punt_lux.tools.tools._get_client")
    @patch.object(DisplayPaths, "is_running", return_value=True)
    def test_list_scenes_timeout(
        self, mock_running: MagicMock, mock_get: MagicMock
    ) -> None:
        client = _mock_client()
        client.query.return_value = None
        mock_get.return_value = client

        result = list_scenes()
        assert result == "timeout"

    @patch("punt_lux.tools.tools._get_client")
    @patch.object(DisplayPaths, "is_running", return_value=True)
    def test_list_scenes_empty(
        self, mock_running: MagicMock, mock_get: MagicMock
    ) -> None:
        client = _mock_client()
        client.query.return_value = QueryResponse(
            method="list_scenes",
            result={"scenes": [], "frames": []},
        )
        mock_get.return_value = client

        result = list_scenes()
        assert '"scenes": []' in result
        assert '"frames": []' in result


class TestScreenshotTool:
    @patch("punt_lux.tools.tools._get_client")
    @patch.object(DisplayPaths, "is_running", return_value=False)
    def test_screenshot_not_running(
        self, mock_running: MagicMock, mock_get: MagicMock
    ) -> None:

        result = screenshot()
        assert result == "not running"
        mock_get.assert_not_called()

    @patch("punt_lux.tools.tools._get_client")
    @patch.object(DisplayPaths, "is_running", return_value=True)
    def test_screenshot_returns_path(
        self, mock_running: MagicMock, mock_get: MagicMock
    ) -> None:
        client = _mock_client()
        client.query.return_value = QueryResponse(
            method="screenshot",
            result={"path": "/tmp/lux-screenshot-abc.png"},
        )
        mock_get.return_value = client

        result = screenshot()
        assert result == "/tmp/lux-screenshot-abc.png"

    @patch("punt_lux.tools.tools._get_client")
    @patch.object(DisplayPaths, "is_running", return_value=True)
    def test_screenshot_error(
        self, mock_running: MagicMock, mock_get: MagicMock
    ) -> None:
        client = _mock_client()
        client.query.return_value = QueryResponse(
            method="screenshot",
            error="OpenGL not available",
        )
        mock_get.return_value = client

        result = screenshot()
        assert result == "error: OpenGL not available"

    @patch("punt_lux.tools.tools._get_client")
    @patch.object(DisplayPaths, "is_running", return_value=True)
    def test_screenshot_timeout(
        self, mock_running: MagicMock, mock_get: MagicMock
    ) -> None:
        client = _mock_client()
        client.query.return_value = None
        mock_get.return_value = client

        result = screenshot()
        assert result == "timeout"


class TestSessionKey:
    def test_default_is_local(self) -> None:
        assert _session_key.get() == "local"

    def test_set_and_reset(self) -> None:
        token = _session_key.set("ws-42")
        try:
            assert _session_key.get() == "ws-42"
        finally:
            _session_key.reset(token)
        assert _session_key.get() == "local"


class TestCleanupSession:
    def test_removes_tracked_items(self) -> None:
        _session_menus["sess-1"] = ["tool-a", "tool-b"]
        _cleanup_session("sess-1")
        assert "sess-1" not in _session_menus

    def test_noop_when_no_items(self) -> None:
        _session_menus.pop("nonexistent", None)
        _cleanup_session("nonexistent")
        assert "nonexistent" not in _session_menus


class TestRegisterToolSessionTracking:
    @patch("punt_lux.tools.tools._get_client")
    def test_tracks_in_session_menus(self, mock_get: MagicMock) -> None:
        client = _mock_client()
        mock_get.return_value = client

        _session_menus.pop("local", None)
        register_tool(label="Run", tool_id="run-btn")
        assert "run-btn" in _session_menus.get("local", [])
        # Cleanup
        _session_menus.pop("local", None)

    @patch("punt_lux.tools.tools._get_client")
    def test_tracks_under_custom_session_key(self, mock_get: MagicMock) -> None:
        client = _mock_client()
        mock_get.return_value = client

        token = _session_key.set("ws-99")
        try:
            _session_menus.pop("ws-99", None)
            register_tool(label="Build", tool_id="build-btn")
            assert "build-btn" in _session_menus.get("ws-99", [])
        finally:
            _session_key.reset(token)
            _session_menus.pop("ws-99", None)
