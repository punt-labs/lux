"""Unit tests for punt_lux.tools — MCP tool functions."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import cast
from unittest.mock import MagicMock, patch

import pytest

from punt_lux.display_client import agent_element_factory
from punt_lux.domain.element import Element as DomainElement
from punt_lux.domain.hub import client_registry, hub
from punt_lux.domain.hub.display_connection import HubDisplayConnection
from punt_lux.domain.hub.element_index import UnknownElementError
from punt_lux.domain.hub.hub_display import HubDisplay
from punt_lux.domain.hub.hub_factory import hub_element_factory
from punt_lux.domain.hub.inbox import ensure_writer, next_event
from punt_lux.domain.hub.menu_registry import HubMenuRegistry
from punt_lux.domain.ids import ConnectionId, ElementId, SceneId
from punt_lux.domain.update import AddElement
from punt_lux.operations import (
    Operations,
    OpError,
    SceneInspection,
    SceneList,
)
from punt_lux.operations.ports import HubPorts
from punt_lux.paths import DisplayPaths
from punt_lux.protocol import (
    CheckboxElement,
    CollapsingHeaderElement,
    ColorPickerElement,
    ComboElement,
    DrawElement,
    GroupElement,
    InputTextElement,
    LegacyGroupElement,
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
    TextElement,
    TreeElement,
    WindowElement,
)
from punt_lux.protocol.messages.observer import ObserverMessage
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
)


class TestElementFromDict:
    def test_text_element(self) -> None:
        elem = agent_element_factory().element_from_dict(
            {"kind": "text", "id": "t1", "content": "Hello", "style": "heading"}
        )
        assert elem.kind == "text"
        assert elem.id == "t1"

    def test_button_element(self) -> None:
        elem = agent_element_factory().element_from_dict(
            {"kind": "button", "id": "b1", "label": "Click"}
        )
        assert elem.kind == "button"

    def test_image_element(self) -> None:
        elem = agent_element_factory().element_from_dict(
            {"kind": "image", "id": "i1", "path": "/img.png"}
        )
        assert elem.kind == "image"

    def test_separator_element(self) -> None:
        elem = agent_element_factory().element_from_dict({"kind": "separator"})
        assert elem.kind == "separator"

    def test_missing_kind_raises(self) -> None:
        with pytest.raises(ValueError, match="kind"):
            agent_element_factory().element_from_dict({"id": "t1", "content": "Hi"})

    def test_text_missing_content_raises(self) -> None:
        # PY-EH-8 / Bug-H + SFH-NEW-1: required wire fields raise a typed
        # ValueError naming the kind and field, no silent default.
        with pytest.raises(ValueError, match=r"text element.*'content'"):
            agent_element_factory().element_from_dict({"kind": "text", "id": "t1"})

    def test_button_defaults_label_to_empty(self) -> None:
        elem = agent_element_factory().element_from_dict({"kind": "button", "id": "b1"})
        assert elem.label == ""

    def test_slider_element(self) -> None:
        elem = agent_element_factory().element_from_dict(
            {"kind": "slider", "id": "sl1", "label": "Vol", "value": 50.0}
        )
        assert elem.kind == "slider"
        assert elem.id == "sl1"

    def test_slider_defaults(self) -> None:
        elem = agent_element_factory().element_from_dict(
            {"kind": "slider", "id": "sl1"}
        )
        assert isinstance(elem, SliderElement)
        assert elem.label == ""
        assert elem.value == 0.0

    def test_checkbox_element(self) -> None:
        elem = agent_element_factory().element_from_dict(
            {"kind": "checkbox", "id": "cb1", "label": "On", "value": True}
        )
        assert isinstance(elem, CheckboxElement)
        assert elem.value is True

    def test_combo_element(self) -> None:
        elem = agent_element_factory().element_from_dict(
            {"kind": "combo", "id": "co1", "label": "Pick", "items": ["A", "B"]}
        )
        assert isinstance(elem, ComboElement)
        assert elem.items == ["A", "B"]

    def test_input_text_element(self) -> None:
        elem = agent_element_factory().element_from_dict(
            {"kind": "input_text", "id": "it1", "label": "Name", "hint": "who?"}
        )
        assert isinstance(elem, InputTextElement)
        assert elem.hint == "who?"

    def test_radio_element(self) -> None:
        elem = agent_element_factory().element_from_dict(
            {"kind": "radio", "id": "r1", "label": "Opt", "items": ["X", "Y"]}
        )
        assert elem.kind == "radio"

    def test_color_picker_element(self) -> None:
        elem = agent_element_factory().element_from_dict(
            {"kind": "color_picker", "id": "cp1", "label": "Bg", "value": "#FF0000"}
        )
        assert isinstance(elem, ColorPickerElement)
        assert elem.value == "#FF0000"

    def test_draw_element(self) -> None:
        elem = agent_element_factory().element_from_dict(
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
        elem = agent_element_factory().element_from_dict({"kind": "draw", "id": "d1"})
        assert isinstance(elem, DrawElement)
        assert elem.width == 400
        assert elem.height == 300
        assert elem.commands == ()

    def test_group_element(self) -> None:
        elem = agent_element_factory().element_from_dict(
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
        elem = agent_element_factory().element_from_dict({"kind": "group", "id": "g1"})
        assert isinstance(elem, GroupElement)
        assert elem.layout == "rows"
        assert elem.children == ()

    def test_tab_bar_element(self) -> None:
        # An all-ABC subtree (a text child) decodes onto the ABC path, where
        # tabs are typed ``Tab`` value objects carrying a stable ``tab_id``.
        elem = agent_element_factory().element_from_dict(
            {
                "kind": "tab_bar",
                "id": "tb1",
                "tabs": [
                    {
                        "id": "tab-a",
                        "label": "A",
                        "children": [{"kind": "text", "id": "t1", "content": "In A"}],
                    },
                ],
            }
        )
        assert isinstance(elem, TabBarElement)
        assert len(elem.tabs) == 1
        assert elem.tabs[0].label == "A"
        assert elem.tabs[0].tab_id == "tab-a"
        assert elem.active_tab == "tab-a"

    def test_collapsing_header_element(self) -> None:
        # An all-ABC subtree (a button child) decodes onto the ABC path, where
        # the Hub-authoritative view field is ``open`` (default_open collapses
        # into it).
        elem = agent_element_factory().element_from_dict(
            {
                "kind": "collapsing_header",
                "id": "ch1",
                "label": "Details",
                "open": True,
                "children": [{"kind": "button", "id": "b1", "label": "Go"}],
            }
        )
        assert isinstance(elem, CollapsingHeaderElement)
        assert elem.label == "Details"
        assert elem.open is True
        assert len(elem.children) == 1

    def test_window_element(self) -> None:
        elem = agent_element_factory().element_from_dict(
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
        elem = agent_element_factory().element_from_dict({"kind": "window", "id": "w1"})
        assert isinstance(elem, WindowElement)
        assert elem.title == ""
        assert elem.width == 300.0
        assert elem.no_move is False
        assert elem.children == []

    def test_selectable_element(self) -> None:
        elem = agent_element_factory().element_from_dict(
            {"kind": "selectable", "id": "s1", "label": "Item", "selected": True}
        )
        assert isinstance(elem, SelectableElement)
        assert elem.label == "Item"
        assert elem.selected is True

    def test_selectable_defaults(self) -> None:
        elem = agent_element_factory().element_from_dict(
            {"kind": "selectable", "id": "s1"}
        )
        assert isinstance(elem, SelectableElement)
        assert elem.label == ""
        assert elem.selected is False

    def test_tree_element(self) -> None:
        elem = agent_element_factory().element_from_dict(
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
        elem = agent_element_factory().element_from_dict({"kind": "tree", "id": "tr1"})
        assert isinstance(elem, TreeElement)
        assert elem.label == ""
        assert elem.nodes == []

    def test_table_element(self) -> None:
        elem = agent_element_factory().element_from_dict(
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
        elem = agent_element_factory().element_from_dict(
            {"kind": "table", "id": "tbl1"}
        )
        assert isinstance(elem, TableElement)
        assert elem.columns == []
        assert elem.rows == []
        assert elem.flags == ["borders", "row_bg"]

    def test_plot_element(self) -> None:
        elem = agent_element_factory().element_from_dict(
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
        elem = agent_element_factory().element_from_dict({"kind": "plot", "id": "p1"})
        assert isinstance(elem, PlotElement)
        assert elem.title == ""
        assert elem.x_label == ""
        assert elem.y_label == ""
        assert elem.width == -1
        assert elem.height == 300
        assert elem.series == []

    def test_progress_element(self) -> None:
        elem = agent_element_factory().element_from_dict(
            {"kind": "progress", "id": "pg1", "fraction": 0.75, "label": "75%"}
        )
        assert isinstance(elem, ProgressElement)
        assert elem.fraction == 0.75
        assert elem.label == "75%"

    def test_progress_missing_fraction_raises(self) -> None:
        # PY-EH-8 / Bug-H + SFH-NEW-1: required wire fields raise a typed
        # ValueError naming the kind and field, no silent default.
        with pytest.raises(ValueError, match=r"progress element.*'fraction'"):
            agent_element_factory().element_from_dict({"kind": "progress", "id": "pg1"})

    def test_progress_label_optional(self) -> None:
        elem = agent_element_factory().element_from_dict(
            {"kind": "progress", "id": "pg1", "fraction": 0.0}
        )
        assert isinstance(elem, ProgressElement)
        assert elem.label == ""

    def test_spinner_element(self) -> None:
        elem = agent_element_factory().element_from_dict(
            {"kind": "spinner", "id": "sp1", "label": "Wait", "radius": 20.0}
        )
        assert isinstance(elem, SpinnerElement)
        assert elem.label == "Wait"
        assert elem.radius == 20.0

    def test_spinner_defaults(self) -> None:
        elem = agent_element_factory().element_from_dict(
            {"kind": "spinner", "id": "sp1"}
        )
        assert isinstance(elem, SpinnerElement)
        assert elem.radius == 16.0
        assert elem.color == "#3399FF"

    def test_markdown_element(self) -> None:
        elem = agent_element_factory().element_from_dict(
            {"kind": "markdown", "id": "md1", "content": "**bold**"}
        )
        assert isinstance(elem, MarkdownElement)
        assert elem.content == "**bold**"

    def test_markdown_missing_content_raises(self) -> None:
        # PY-EH-8 / Bug-H + SFH-NEW-1: required wire fields raise a typed
        # ValueError naming the kind and field, no silent default.
        with pytest.raises(ValueError, match=r"markdown element.*'content'"):
            agent_element_factory().element_from_dict({"kind": "markdown", "id": "md1"})

    def test_tooltip_from_dict(self) -> None:
        elem = agent_element_factory().element_from_dict(
            {"kind": "text", "id": "t1", "content": "hi", "tooltip": "help"}
        )
        assert elem.tooltip == "help"

    def test_tooltip_default_none(self) -> None:
        elem = agent_element_factory().element_from_dict(
            {"kind": "text", "id": "t1", "content": "hi"}
        )
        assert elem.tooltip is None

    def test_unknown_kind_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown element kind"):
            agent_element_factory().element_from_dict({"kind": "bogus", "id": "x"})


def _mock_client() -> MagicMock:
    client = MagicMock()
    client.is_connected = True
    return client


def _bad_table(element_id: str = "bad") -> dict[str, object]:
    """A table dict whose single row is short — one validation error."""
    return {
        "kind": "table",
        "id": element_id,
        "columns": ["A", "B"],
        "rows": [["only-one"]],
    }


class TestSetMenuTool:
    def test_set_menu_writes_the_hub_registry(self) -> None:
        # set_menu is a Hub write now: it stores the bar in the Hub menu
        # registry (the replicator pushes it) instead of reaching the display.
        from punt_lux.domain.hub.menu_registry import hub_menu_registry

        menus = [{"label": "Tools", "items": [{"label": "Run", "id": "run"}]}]
        try:
            result = set_menu(menus)
            assert result == "ok"
            assert any(m.get("label") == "Tools" for m in hub_menu_registry.menu_bar())
        finally:
            hub_menu_registry.set_menus([])


class TestSetThemeTool:
    @patch.object(DisplayPaths, "is_running", return_value=True)
    @patch("punt_lux.domain.hub.clients.client_registry.get")
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

    @patch("punt_lux.domain.hub.clients.client_registry.drop")
    @patch.object(DisplayPaths, "is_running", return_value=True)
    @patch("punt_lux.domain.hub.clients.client_registry.get")
    def test_set_theme_timeout_drops_the_dead_connection(
        self, mock_get: MagicMock, _mock_running: MagicMock, mock_drop: MagicMock
    ) -> None:
        # A5: a wedged or dead display makes the bounded round-trip raise OSError.
        # The tool reports "timeout" and drops the connection so the next set_*
        # reconnects, instead of reusing the dead fd forever.
        client = _mock_client()
        client.query.side_effect = OSError("EPIPE")
        mock_get.return_value = client

        result = set_theme("imgui_colors_light")
        assert result == "timeout"
        mock_drop.assert_called_once()


class TestShowTool:
    def test_show_marks_the_scene_dirty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        store = HubDisplay()
        client = _bind_store(monkeypatch, store)

        result = show("s1", [{"kind": "text", "id": "t1", "content": "Hi"}])

        assert result == "shown:s1"
        assert client.replicator.dirtied == [SceneId("s1")]

    def test_show_returns_shown_without_waiting_on_the_display(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store = HubDisplay()
        client = _bind_store(monkeypatch, store)

        result = show("s1", [{"kind": "text", "id": "t1", "content": "Hi"}])

        # The tool never contacts the display — it writes the Hub and returns.
        assert result == "shown:s1"
        client.show.assert_not_called()

    def test_show_installs_scene_in_the_hub_store(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store = HubDisplay()
        _bind_store(monkeypatch, store)

        show("s1", [{"kind": "text", "id": "t1", "content": "Hi"}])

        # The authoritative store carries the scene before any send happens.
        assert store.resolve(SceneId("s1"), ElementId("t1")).id == "t1"

    def test_show_records_the_frame_for_the_scene(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store = HubDisplay()
        _bind_store(monkeypatch, store)

        show(
            "s1",
            [{"kind": "text", "id": "t1", "content": "Hi"}],
            frame_id="dash",
        )

        # The recorded presentation is what the replicator resends the scene with.
        assert store.presentation_for(SceneId("s1")).frame_id == "dash"

    @patch("punt_lux.domain.hub.clients.client_registry.get")
    def test_show_rejects_an_unknown_layout(self, mock_get: MagicMock) -> None:
        # An out-of-set layout is rejected at the wire boundary before anything is
        # installed — the error names the allowed values and the client is never
        # touched, so a typo cannot reach the store or the display.
        client = _mock_client()
        mock_get.return_value = client

        result = show("s1", [], layout="diagonal")

        assert result == (
            "error: layout must be single/rows/columns/grid, got 'diagonal'"
        )
        client.show.assert_not_called()

    def test_show_valid_table_renders(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Demonstration (a): a well-formed table validates clean and is accepted.
        store = HubDisplay()
        client = _bind_store(monkeypatch, store)

        result = show(
            "s1",
            [
                {
                    "kind": "table",
                    "id": "sales",
                    "columns": ["Name", "Score"],
                    "rows": [["Alice", 95], ["Bob", 87]],
                },
            ],
        )
        assert result == "shown:s1"
        assert client.replicator.dirtied == [SceneId("s1")]

    @patch("punt_lux.domain.hub.clients.client_registry.get")
    def test_show_rejects_table_with_mismatched_row(self, mock_get: MagicMock) -> None:
        # Demonstration (b): a short row collects an actionable error and the
        # tree is NOT rendered — the client is never called.
        client = _mock_client()
        mock_get.return_value = client

        result = show(
            "s1",
            [
                {
                    "kind": "table",
                    "id": "sales",
                    "columns": ["Name", "Score", "Rank"],
                    "rows": [["Alice", 95]],
                },
            ],
        )
        assert result.startswith("error: scene not rendered")
        assert "[table 'sales']" in result
        assert "2 cell(s)" in result
        assert "3 column(s)" in result
        client.show.assert_not_called()

    @patch("punt_lux.domain.hub.clients.client_registry.get")
    def test_show_collects_error_from_table_nested_in_group(
        self, mock_get: MagicMock
    ) -> None:
        # Demonstration (c): a bad table nested in a group beside a valid
        # element — the walk collects the table's error across the hierarchy.
        client = _mock_client()
        mock_get.return_value = client

        result = show(
            "s1",
            [
                {
                    "kind": "group",
                    "id": "g1",
                    "children": [
                        {"kind": "text", "id": "ok", "content": "fine"},
                        {
                            "kind": "table",
                            "id": "nested",
                            "columns": ["A", "B"],
                            "rows": [["only-one"]],
                        },
                    ],
                },
            ],
        )
        assert result.startswith("error: scene not rendered")
        assert "[table 'nested']" in result
        assert "1 validation error(s):" in result
        client.show.assert_not_called()

    @patch("punt_lux.domain.hub.clients.client_registry.get")
    def test_show_rejects_bad_table_nested_in_window(self, mock_get: MagicMock) -> None:
        client = _mock_client()
        mock_get.return_value = client

        result = show(
            "s1",
            [
                {
                    "kind": "window",
                    "id": "w1",
                    "children": [_bad_table("in_window")],
                },
            ],
        )
        assert result.startswith("error: scene not rendered")
        assert "[table 'in_window']" in result
        client.show.assert_not_called()

    @patch("punt_lux.domain.hub.clients.client_registry.get")
    def test_show_rejects_bad_table_nested_in_tab_bar(
        self, mock_get: MagicMock
    ) -> None:
        client = _mock_client()
        mock_get.return_value = client

        result = show(
            "s1",
            [
                {
                    "kind": "tab_bar",
                    "id": "tb1",
                    "tabs": [{"label": "One", "children": [_bad_table("in_tab")]}],
                },
            ],
        )
        assert result.startswith("error: scene not rendered")
        assert "[table 'in_tab']" in result
        client.show.assert_not_called()

    @patch("punt_lux.domain.hub.clients.client_registry.get")
    def test_show_rejects_bad_table_nested_in_collapsing_header(
        self, mock_get: MagicMock
    ) -> None:
        client = _mock_client()
        mock_get.return_value = client

        result = show(
            "s1",
            [
                {
                    "kind": "collapsing_header",
                    "id": "ch1",
                    "label": "Details",
                    "children": [_bad_table("in_header")],
                },
            ],
        )
        assert result.startswith("error: scene not rendered")
        assert "[table 'in_header']" in result
        client.show.assert_not_called()

    @patch("punt_lux.domain.hub.clients.client_registry.get")
    def test_show_rejects_bad_table_nested_in_modal(self, mock_get: MagicMock) -> None:
        client = _mock_client()
        mock_get.return_value = client

        result = show(
            "s1",
            [
                {
                    "kind": "modal",
                    "id": "m1",
                    "title": "Confirm",
                    "children": [_bad_table("in_modal")],
                },
            ],
        )
        assert result.startswith("error: scene not rendered")
        assert "[table 'in_modal']" in result
        client.show.assert_not_called()

    @patch("punt_lux.domain.hub.clients.client_registry.get")
    def test_show_rejects_tree_with_malformed_node(self, mock_get: MagicMock) -> None:
        # A tree's nodes are mappings, not elements — the tree self-validates
        # its own structure. A node that is not a mapping is reported, not
        # silently dropped, and the scene is never rendered.
        client = _mock_client()
        mock_get.return_value = client

        result = show(
            "s1",
            [{"kind": "tree", "id": "files", "label": "Files", "nodes": [42]}],
        )
        assert result.startswith("error: scene not rendered")
        assert "[tree 'files']" in result
        assert "node 0 is not a mapping" in result
        client.show.assert_not_called()

    @patch("punt_lux.domain.hub.clients.client_registry.get")
    def test_show_recurses_three_levels_deep(self, mock_get: MagicMock) -> None:
        # container -> container -> bad leaf: the walk reaches a table two
        # containers down and still collects its error.
        client = _mock_client()
        mock_get.return_value = client

        result = show(
            "s1",
            [
                {
                    "kind": "window",
                    "id": "w1",
                    "children": [
                        {
                            "kind": "collapsing_header",
                            "id": "ch1",
                            "label": "Nested",
                            "children": [_bad_table("deep")],
                        },
                    ],
                },
            ],
        )
        assert result.startswith("error: scene not rendered")
        assert "[table 'deep']" in result
        client.show.assert_not_called()

    @patch("punt_lux.domain.hub.clients.client_registry.get")
    def test_show_aggregates_two_bad_tables(self, mock_get: MagicMock) -> None:
        client = _mock_client()
        mock_get.return_value = client

        result = show("s1", [_bad_table("first"), _bad_table("second")])
        assert result.startswith("error: scene not rendered")
        assert "[table 'first']" in result
        assert "[table 'second']" in result
        assert "2 validation error(s):" in result
        client.show.assert_not_called()

    @patch("punt_lux.domain.hub.clients.client_registry.get")
    def test_show_rejects_bad_table_on_group_page(self, mock_get: MagicMock) -> None:
        # A group's non-active pages are still installed into the scene, so a
        # bad table hidden on a page must be caught end-to-end through show() —
        # the exact "invalid element on a non-active page" case GroupElement's
        # paged child exposure exists to cover.
        client = _mock_client()
        mock_get.return_value = client

        result = show(
            "s1",
            [
                {
                    "kind": "group",
                    "id": "g1",
                    "children": [{"kind": "text", "id": "nav", "content": "page 1"}],
                    "pages": [[_bad_table("on_page")]],
                },
            ],
        )
        assert result.startswith("error: scene not rendered")
        assert "[table 'on_page']" in result
        client.show.assert_not_called()


class TestShowTableTool:
    def test_show_table_minimal(self, monkeypatch: pytest.MonkeyPatch) -> None:
        store = HubDisplay()
        _bind_store(monkeypatch, store)

        result = show_table(
            "t1",
            columns=["Name", "Score"],
            rows=[["Alice", 95], ["Bob", 87]],
        )
        assert result == "shown:t1"
        elements: list[object] = list(store.scene_roots(SceneId("t1")))
        assert len(elements) == 1
        table = elements[0]
        assert isinstance(table, TableElement)
        assert table.columns == ["Name", "Score"]
        assert table.flags == ["borders", "row_bg"]

    def test_show_table_with_filters_and_detail(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store = HubDisplay()
        _bind_store(monkeypatch, store)

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
        assert result == "shown:t2"
        table: object = store.scene_roots(SceneId("t2"))[0]
        assert isinstance(table, TableElement)
        assert table.filters is not None
        assert len(table.filters) == 2
        assert table.detail is not None
        assert table.detail.fields == ["ID", "Status"]

    def test_show_table_custom_flags(self, monkeypatch: pytest.MonkeyPatch) -> None:
        store = HubDisplay()
        _bind_store(monkeypatch, store)

        show_table("t3", columns=["A"], rows=[["x"]], flags=["borders", "resizable"])

        table: object = store.scene_roots(SceneId("t3"))[0]
        assert isinstance(table, TableElement)
        assert table.flags == ["borders", "resizable"]


class TestShowDashboardTool:
    def test_dashboard_metrics_only(self, monkeypatch: pytest.MonkeyPatch) -> None:
        store = HubDisplay()
        _bind_store(monkeypatch, store)

        result = show_dashboard(
            "d1",
            metrics=[
                {"label": "Users", "value": "100"},
                {"label": "Revenue", "value": "$5k"},
            ],
        )
        assert result == "shown:d1"
        elements: list[object] = list(store.scene_roots(SceneId("d1")))
        # metrics group only (no trailing separator for single section)
        assert len(elements) == 1
        group = elements[0]
        assert isinstance(group, GroupElement)
        assert len(group.children) == 2

    def test_dashboard_all_sections(self, monkeypatch: pytest.MonkeyPatch) -> None:
        store = HubDisplay()
        _bind_store(monkeypatch, store)

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
        kinds = [e.kind for e in store.scene_roots(SceneId("d2"))]
        assert "group" in kinds  # metrics
        assert "plot" in kinds  # chart
        assert "table" in kinds  # table
        assert kinds.count("separator") == 2

    def test_dashboard_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        store = HubDisplay()
        _bind_store(monkeypatch, store)

        result = show_dashboard("d3")

        assert result == "shown:d3"
        assert store.scene_roots(SceneId("d3")) == []


def _seed_store(
    store: HubDisplay,
    *,
    scene: str = "s1",
    header_id: str = "hdr",
    is_open: bool = False,
    label: str = "Details",
) -> CollapsingHeaderElement:
    """Install one Hub-authoritative collapsing header under connection 'local'.

    'local' is the default ``_session_key``, so the tools resolve the same owner
    that seeded the scene. The header's ``open`` flag is the Hub-authoritative
    field an agent drives through ``update``.
    """
    header = CollapsingHeaderElement(id=header_id, label=label, open=is_open)
    store.replace_scene(ConnectionId("local"), SceneId(scene), [header])
    return header


class _ReplicatorSpy:
    """Records mark_dirty / mark_cleared — the tool's only contact with sends."""

    dirtied: list[SceneId]
    cleared: int
    __slots__ = ("cleared", "dirtied")

    def __new__(cls) -> _ReplicatorSpy:
        self = super().__new__(cls)
        self.dirtied = []
        self.cleared = 0
        return self

    def mark_dirty(self, scene_id: SceneId) -> None:
        self.dirtied.append(scene_id)

    def mark_cleared(self) -> None:
        self.cleared += 1

    def mark_menus(self, bar: object, items: object) -> None:
        """Swallow a menu push mark; the spy only records scene signals."""


def _bind_store(monkeypatch: pytest.MonkeyPatch, store: HubDisplay) -> MagicMock:
    """Route the operations at one isolated store and a recording replicator.

    ``show`` / ``update`` / ``clear`` reach the store through the ``OPERATIONS``
    facade the tools import. Binding a facade over one isolated store and a
    recording replicator keeps the singletons out of the test; the spy is
    attached to the returned client as ``client.replicator``.
    """
    spy = _ReplicatorSpy()
    ops = Operations.for_store(
        store,
        spy,
        hub=hub,
        client_registry=client_registry,
        menu_registry=HubMenuRegistry(),
        ports=HubPorts(
            element_factory=hub_element_factory,
            ensure_writer=ensure_writer,
            next_event=next_event,
        ),
        display_port=HubDisplayConnection(
            is_running=lambda: DisplayPaths().is_running(),
            clients=client_registry,
        ),
    )
    monkeypatch.setattr("punt_lux.tools.tools.OPERATIONS", ops)
    client = _mock_client()
    monkeypatch.setattr(
        "punt_lux.domain.hub.clients.client_registry.get", lambda: client
    )
    client.replicator = spy
    return client


def _bind_pubsub(
    monkeypatch: pytest.MonkeyPatch,
    next_fn: Callable[[ConnectionId, float], ObserverMessage | None],
) -> None:
    """Route the pub-sub adapters at a facade whose inbox is ``next_fn``."""

    def _no_writer(_connection_id: ConnectionId) -> None:
        return None

    ops = Operations.for_store(
        HubDisplay(),
        _ReplicatorSpy(),
        hub=hub,
        client_registry=client_registry,
        menu_registry=HubMenuRegistry(),
        ports=HubPorts(
            element_factory=hub_element_factory,
            ensure_writer=_no_writer,
            next_event=next_fn,
        ),
        display_port=HubDisplayConnection(
            is_running=lambda: DisplayPaths().is_running(),
            clients=client_registry,
        ),
    )
    monkeypatch.setattr("punt_lux.tools.subscribe_tools.OPERATIONS", ops)


def _seed_group_with_child(
    store: HubDisplay,
    *,
    scene: str = "s1",
    group_id: str = "g1",
    child_id: str = "t1",
    content: str = "hi",
    connection: str = "local",
) -> None:
    """Install a group root with one ABC text child under ``connection``.

    The child is a non-root id the Hub installs and owns via subtree recursion,
    so ``update`` can patch it through the same ownership + resolve path a root
    takes.
    """
    group = agent_element_factory().element_from_dict(
        {
            "kind": "group",
            "id": group_id,
            "children": [{"kind": "text", "id": child_id, "content": content}],
        }
    )
    store.replace_scene(
        ConnectionId(connection),
        SceneId(scene),
        [cast("DomainElement", group)],
    )


def _seed_legacy_root(
    store: HubDisplay,
    *,
    scene: str = "s1",
    element_id: str = "sl1",
    label: str = "opt",
    connection: str = "local",
) -> None:
    """Install one legacy (non-ABC) spinner root under ``connection``.

    A frozen wire dataclass is realized by ``dataclasses.replace`` on the write
    path — a legacy *root* is fully patchable, and its index entry is rebound to
    the fresh instance.
    """
    spinner = agent_element_factory().element_from_dict(
        {
            "kind": "spinner",
            "id": element_id,
            "label": label,
        }
    )
    store.replace_scene(
        ConnectionId(connection),
        SceneId(scene),
        [cast("DomainElement", spinner)],
    )


def _seed_legacy_window_with_child(
    store: HubDisplay,
    *,
    scene: str = "s1",
    window_id: str = "w1",
    child_id: str = "sl_child",
    title: str = "Old",
    connection: str = "local",
) -> SpinnerElement:
    """Install a legacy window root holding one legacy spinner child.

    A legacy composite: the whole subtree is frozen values, so a ``replace`` on
    the root shares the child by reference. Returns the child object so a test
    can assert its identity survives a root patch.
    """
    child = SpinnerElement(id=child_id, label="Vol")
    window = WindowElement(id=window_id, title=title, children=[child])
    store.replace_scene(
        ConnectionId(connection),
        SceneId(scene),
        [cast("DomainElement", window)],
    )
    return child


def _seed_legacy_group_with_child(
    store: HubDisplay,
    *,
    scene: str = "s1",
    group_id: str = "grp",
    child_id: str = "c1",
    connection: str = "local",
) -> TextElement:
    """Install a legacy group root holding one legacy text child.

    A ``LegacyGroupElement`` carries child Elements in ``children`` (and, when
    paged, ``pages``). Returns the child so a test can assert it survives — and no
    new child is installed — after a rejected structural patch.
    """
    child = TextElement(id=child_id, content="old")
    group = LegacyGroupElement(id=group_id, children=[child])
    store.replace_scene(
        ConnectionId(connection),
        SceneId(scene),
        [cast("DomainElement", group)],
    )
    return child


class TestUpdateTool:
    def test_update_writes_hub_store_and_marks_dirty(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An agent ``update`` mutates the authoritative store and marks it dirty."""
        store = HubDisplay()
        _seed_store(store, is_open=False)
        client = _bind_store(monkeypatch, store)

        result = update("s1", [{"id": "hdr", "set": {"open": True}}])

        assert result == "shown:s1"
        # Authoritative store — NOT a display copy — carries the new value.
        header = store.resolve(SceneId("s1"), ElementId("hdr"))
        assert isinstance(header, CollapsingHeaderElement)
        assert header.open is True
        # The scene is marked dirty; the replicator resends it from the store.
        assert client.replicator.dirtied == [SceneId("s1")]

    def test_update_remove_drops_element_from_hub_store(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A ``remove`` patch evicts the element from the authoritative store."""
        store = HubDisplay()
        _seed_store(store)
        client = _bind_store(monkeypatch, store)

        result = update("s1", [{"id": "hdr", "remove": True}])

        assert result == "shown:s1"
        assert store.scene_roots(SceneId("s1")) == []
        with pytest.raises(LookupError):
            store.resolve(SceneId("s1"), ElementId("hdr"))
        assert client.replicator.dirtied == [SceneId("s1")]

    def test_update_rejects_patch_that_invalidates_element(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A patch that fails the element's self-validation is rejected in full."""
        store = HubDisplay()
        _seed_store(store, label="Details")
        client = _bind_store(monkeypatch, store)

        result = update("s1", [{"id": "hdr", "set": {"label": ""}}])

        assert result.startswith("error: scene not updated")
        # The authoritative store is untouched; nothing is re-pushed.
        header = store.resolve(SceneId("s1"), ElementId("hdr"))
        assert isinstance(header, CollapsingHeaderElement)
        assert header.label == "Details"
        client.show_async.assert_not_called()

    def test_update_unknown_element_is_rejected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Patching an id the Hub never installed fails loud, not silently."""
        store = HubDisplay()
        _seed_store(store)
        client = _bind_store(monkeypatch, store)

        result = update("s1", [{"id": "ghost", "set": {"open": True}}])

        assert result.startswith("error: scene not updated")
        # The store is untouched — the seeded header survives the rejection.
        assert store.resolve(SceneId("s1"), ElementId("hdr")).id == "hdr"
        client.show_async.assert_not_called()

    def test_update_rejects_patch_with_no_set_and_no_remove(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A patch that is neither a removal nor a ``set`` mapping is rejected.

        The old ``from_wire`` silently dropped such a patch and still acked; now
        the whole batch is refused and the offending id is named.
        """
        store = HubDisplay()
        _seed_store(store)
        client = _bind_store(monkeypatch, store)

        result = update("s1", [{"id": "hdr"}])

        assert result.startswith("error: scene not updated")
        assert "hdr" in result
        client.show_async.assert_not_called()

    def test_update_rejects_set_that_is_not_a_mapping(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A ``set`` whose value is not a mapping is rejected, not dropped."""
        store = HubDisplay()
        _seed_store(store)
        client = _bind_store(monkeypatch, store)

        result = update("s1", [{"id": "hdr", "set": "not-a-map"}])

        assert result.startswith("error: scene not updated")
        assert "hdr" in result
        client.show_async.assert_not_called()

    def test_update_rejects_remove_false_with_no_set(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A falsy ``remove`` with no ``set`` is malformed, not a silent no-op."""
        store = HubDisplay()
        _seed_store(store)
        client = _bind_store(monkeypatch, store)

        result = update("s1", [{"id": "hdr", "remove": False}])

        assert result.startswith("error: scene not updated")
        assert "hdr" in result
        client.show_async.assert_not_called()

    def test_update_rejects_remove_and_set_together(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A patch carrying both ``remove`` and ``set`` is refused whole.

        The old ``from_wire`` took the truthy ``remove`` and silently discarded
        the ``set``; now the mutually-exclusive shape is rejected and the store
        is untouched.
        """
        store = HubDisplay()
        _seed_store(store)
        client = _bind_store(monkeypatch, store)

        result = update("s1", [{"id": "hdr", "remove": True, "set": {"open": True}}])

        assert result.startswith("error: scene not updated")
        assert "hdr" in result
        # The seeded header survives untouched.
        header = store.resolve(SceneId("s1"), ElementId("hdr"))
        assert isinstance(header, CollapsingHeaderElement)
        assert header.open is False
        client.show_async.assert_not_called()

    def test_update_rejects_non_boolean_remove(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A truthy but non-boolean ``remove`` (``"yes"``) is refused loud.

        The old ``from_wire`` treated any truthy value as a removal, so
        ``{"remove": "yes"}`` silently dropped the element; now it is rejected.
        """
        store = HubDisplay()
        _seed_store(store)
        client = _bind_store(monkeypatch, store)

        result = update("s1", [{"id": "hdr", "remove": "yes"}])

        assert result.startswith("error: scene not updated")
        assert "hdr" in result
        # The seeded header survives — the malformed remove never landed.
        assert store.resolve(SceneId("s1"), ElementId("hdr")).id == "hdr"
        client.show_async.assert_not_called()

    def test_update_rejects_patch_missing_id(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A patch with no ``id`` is a clean rejection, not a raw ``KeyError``."""
        store = HubDisplay()
        _seed_store(store)
        client = _bind_store(monkeypatch, store)

        result = update("s1", [{"set": {"open": True}}])

        assert result.startswith("error: scene not updated")
        assert "id" in result
        client.show_async.assert_not_called()

    def test_update_merges_duplicate_id_patches(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Two patches on one id merge and commit as a single unit."""
        store = HubDisplay()
        _seed_store(store, is_open=False, label="Details")
        client = _bind_store(monkeypatch, store)

        result = update(
            "s1",
            [
                {"id": "hdr", "set": {"open": True}},
                {"id": "hdr", "set": {"label": "Renamed"}},
            ],
        )

        assert result == "shown:s1"
        header = store.resolve(SceneId("s1"), ElementId("hdr"))
        assert isinstance(header, CollapsingHeaderElement)
        assert header.open is True
        assert header.label == "Renamed"
        assert client.replicator.dirtied == [SceneId("s1")]

    def test_update_duplicate_id_cumulative_invalid_is_rejected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Two patches whose merged result is invalid reject the whole batch.

        Each patch alone is well-typed, but their cumulative effect (an empty
        label) fails self-validation. The merged patch validates once as a unit,
        so neither half lands and the store keeps its original value.
        """
        store = HubDisplay()
        _seed_store(store, is_open=False, label="Details")
        client = _bind_store(monkeypatch, store)

        result = update(
            "s1",
            [
                {"id": "hdr", "set": {"open": True}},
                {"id": "hdr", "set": {"label": ""}},
            ],
        )

        assert result.startswith("error: scene not updated")
        header = store.resolve(SceneId("s1"), ElementId("hdr"))
        assert isinstance(header, CollapsingHeaderElement)
        assert header.open is False
        assert header.label == "Details"
        client.show_async.assert_not_called()

    def test_update_batch_one_invalid_leaves_valid_untouched(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A multi-element batch with one invalid patch commits nothing."""
        store = HubDisplay()
        first = CollapsingHeaderElement(id="a", label="First", open=False)
        second = CollapsingHeaderElement(id="b", label="Second", open=False)
        store.replace_scene(
            ConnectionId("local"),
            SceneId("s1"),
            [cast("DomainElement", first), cast("DomainElement", second)],
        )
        client = _bind_store(monkeypatch, store)

        result = update(
            "s1",
            [
                {"id": "a", "set": {"open": True}},
                {"id": "b", "set": {"label": ""}},
            ],
        )

        assert result.startswith("error: scene not updated")
        valid = store.resolve(SceneId("s1"), ElementId("a"))
        assert isinstance(valid, CollapsingHeaderElement)
        assert valid.open is False
        client.show_async.assert_not_called()

    def test_update_mixed_valid_remove_and_invalid_set_skips_removal(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An invalid set in the batch prevents an otherwise-valid removal."""
        store = HubDisplay()
        keep = CollapsingHeaderElement(id="keep", label="Keep", open=False)
        drop = CollapsingHeaderElement(id="drop", label="Drop", open=False)
        store.replace_scene(
            ConnectionId("local"),
            SceneId("s1"),
            [cast("DomainElement", keep), cast("DomainElement", drop)],
        )
        client = _bind_store(monkeypatch, store)

        result = update(
            "s1",
            [
                {"id": "drop", "remove": True},
                {"id": "keep", "set": {"label": ""}},
            ],
        )

        assert result.startswith("error: scene not updated")
        # The removal never happened — the invalid set rejects the whole batch.
        assert store.resolve(SceneId("s1"), ElementId("drop")).id == "drop"
        client.show_async.assert_not_called()

    def test_update_mutates_once_and_marks_dirty_once(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The remove runs once and the scene is marked dirty once — no re-drive.

        With mark-and-return there is no push-retry region that could re-drive
        the mutation against an already-deleted id: update mutates the store and
        signals the replicator exactly once, then returns.
        """
        store = HubDisplay()
        _seed_store(store)
        client = _bind_store(monkeypatch, store)

        result = update("s1", [{"id": "hdr", "remove": True}])

        assert result == "shown:s1"
        assert store.scene_roots(SceneId("s1")) == []
        with pytest.raises(LookupError):
            store.resolve(SceneId("s1"), ElementId("hdr"))
        assert client.replicator.dirtied == [SceneId("s1")]

    def test_update_cross_connection_ownership_is_rejected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A set against an element owned by another connection is refused."""
        store = HubDisplay()
        _seed_store(store, is_open=False)  # owned by "local"
        client = _bind_store(monkeypatch, store)

        token = _session_key.set("intruder")
        try:
            result = update("s1", [{"id": "hdr", "set": {"open": True}}])
        finally:
            _session_key.reset(token)

        assert result.startswith("error: scene not updated")
        header = store.resolve(SceneId("s1"), ElementId("hdr"))
        assert isinstance(header, CollapsingHeaderElement)
        assert header.open is False
        client.show_async.assert_not_called()

    def test_update_cross_connection_remove_is_rejected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A remove against another connection's element is refused, untouched."""
        store = HubDisplay()
        _seed_store(store)  # owned by "local"
        client = _bind_store(monkeypatch, store)

        token = _session_key.set("intruder")
        try:
            result = update("s1", [{"id": "hdr", "remove": True}])
        finally:
            _session_key.reset(token)

        assert result.startswith("error: scene not updated")
        assert store.resolve(SceneId("s1"), ElementId("hdr")).id == "hdr"
        client.show_async.assert_not_called()

    def test_update_patches_nested_child(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A non-root child inside a container is patchable through ``update``."""
        store = HubDisplay()
        _seed_group_with_child(store, child_id="t1", content="hi")
        client = _bind_store(monkeypatch, store)

        result = update("s1", [{"id": "t1", "set": {"content": "updated"}}])

        assert result == "shown:s1"
        child = store.resolve(SceneId("s1"), ElementId("t1"))
        assert isinstance(child, TextElement)
        assert child.content == "updated"
        assert client.replicator.dirtied == [SceneId("s1")]

    def test_update_patches_legacy_root_via_replace(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A legacy (frozen) root is written by ``replace`` and its index rebound.

        The store rebinds the root's index entry to the fresh instance under the
        same id, and the re-push carries the new value rebuilt from the store.
        """
        store = HubDisplay()
        _seed_legacy_root(store, element_id="sl1", label="opt")
        client = _bind_store(monkeypatch, store)

        result = update("s1", [{"id": "sl1", "set": {"label": "New"}}])

        assert result == "shown:s1"
        spinner = store.resolve(SceneId("s1"), ElementId("sl1"))
        assert isinstance(spinner, SpinnerElement)
        assert spinner.label == "New"
        assert client.replicator.dirtied == [SceneId("s1")]

    def test_update_legacy_composite_root_shares_children_by_reference(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Patching a legacy composite root shares its children by reference.

        ``dataclasses.replace`` overrides only the addressed field; the fresh
        root's children are the same objects, still reachable by their stable
        ids, so a root patch never rebuilds or re-identifies the subtree.
        """
        store = HubDisplay()
        child = _seed_legacy_window_with_child(
            store, window_id="w1", child_id="sl_child", title="Old"
        )
        client = _bind_store(monkeypatch, store)

        result = update("s1", [{"id": "w1", "set": {"title": "New"}}])

        assert result == "shown:s1"
        window = cast("WindowElement", store.resolve(SceneId("s1"), ElementId("w1")))
        assert window.title == "New"
        # The child object survives the root patch by reference — same identity,
        # still resolvable by its stable id.
        assert window.children[0] is child
        assert store.resolve(SceneId("s1"), ElementId("sl_child")) is child
        assert client.replicator.dirtied == [SceneId("s1")]

    def test_update_nested_legacy_defers_to_show(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A patch on a legacy element below a legacy composite defers to ``show``.

        Rebuilding the frozen spine is deliberately not built for the mixed
        period; the rejection names the enclosing root's kind and directs the
        client to resend the whole tree. The store is untouched, nothing pushed.
        """
        store = HubDisplay()
        child = _seed_legacy_window_with_child(
            store, window_id="w1", child_id="sl_child"
        )
        client = _bind_store(monkeypatch, store)

        result = update("s1", [{"id": "sl_child", "set": {"label": "New"}}])

        assert result.startswith("error: scene not updated")
        assert "show" in result
        assert "window" in result
        # Store untouched — the nested child keeps its original value and identity.
        assert store.resolve(SceneId("s1"), ElementId("sl_child")) is child
        assert child.label == "Vol"
        client.show_async.assert_not_called()

    def test_update_nested_legacy_removal_defers_to_show(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Removing a legacy element below a legacy composite defers to ``show``."""
        store = HubDisplay()
        _seed_legacy_window_with_child(store, window_id="w1", child_id="sl_child")
        client = _bind_store(monkeypatch, store)

        result = update("s1", [{"id": "sl_child", "remove": True}])

        assert result.startswith("error: scene not updated")
        assert "show" in result
        assert store.resolve(SceneId("s1"), ElementId("sl_child")).id == "sl_child"
        client.show_async.assert_not_called()

    def test_update_rejects_immutable_id_field_abc(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A ``set`` targeting ``id`` on an ABC element is refused, untouched."""
        store = HubDisplay()
        _seed_store(store)
        client = _bind_store(monkeypatch, store)

        result = update("s1", [{"id": "hdr", "set": {"id": "renamed"}}])

        assert result.startswith("error: scene not updated")
        assert "immutable" in result
        assert store.resolve(SceneId("s1"), ElementId("hdr")).id == "hdr"
        client.show_async.assert_not_called()

    def test_update_rejects_immutable_kind_field_legacy(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A ``set`` targeting ``kind`` on a legacy root is refused, untouched.

        ``kind`` is a real dataclass field on a legacy element, so without the
        uniform immutability gate ``replace`` would silently morph its type.
        """
        store = HubDisplay()
        _seed_legacy_root(store, element_id="sl1")
        client = _bind_store(monkeypatch, store)

        result = update("s1", [{"id": "sl1", "set": {"kind": "button"}}])

        assert result.startswith("error: scene not updated")
        assert "immutable" in result
        assert store.resolve(SceneId("s1"), ElementId("sl1")).kind == "spinner"
        client.show_async.assert_not_called()

    def test_update_rejects_unknown_field_abc(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An unknown field on an ABC element is a clean rejection."""
        store = HubDisplay()
        _seed_store(store)
        client = _bind_store(monkeypatch, store)

        result = update("s1", [{"id": "hdr", "set": {"nonexistent": 1}}])

        assert result.startswith("error: scene not updated")
        assert "unknown field" in result
        client.show_async.assert_not_called()

    def test_update_rejects_unknown_field_legacy(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An unknown field on a legacy root is rejected as on the ABC path.

        ``replace`` raises ``TypeError`` on an unexpected keyword; the write path
        turns that into the same clean, uniform ``unknown field`` rejection.
        """
        store = HubDisplay()
        _seed_legacy_root(store, element_id="sl1")
        client = _bind_store(monkeypatch, store)

        result = update("s1", [{"id": "sl1", "set": {"bogus": 1}}])

        assert result.startswith("error: scene not updated")
        assert "unknown field" in result
        client.show_async.assert_not_called()

    def test_update_rejects_structural_children_field(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Patching ``children`` on a legacy composite root defers to ``show``.

        The value-replacement seam rebinds only the root's index entry — it installs
        no new children and evicts no old ones. Accepting the patch would render a
        child the Hub index does not know (a dead interaction) and strand the old
        one. So a structural field is refused before any mutation: the old child
        still resolves, no new child id is installed, and nothing is re-pushed.
        """
        store = HubDisplay()
        child = _seed_legacy_group_with_child(store, group_id="grp", child_id="c1")
        client = _bind_store(monkeypatch, store)

        result = update(
            "s1",
            [{"id": "grp", "set": {"children": [{"kind": "text", "id": "d1"}]}}],
        )

        assert result.startswith("error: scene not updated")
        assert "show" in result
        assert "children" in result
        resolved = store.resolve(SceneId("s1"), ElementId("grp"))
        group = cast("LegacyGroupElement", resolved)
        assert group.children == [child]
        assert store.resolve(SceneId("s1"), ElementId("c1")) is child
        with pytest.raises(UnknownElementError):
            store.resolve(SceneId("s1"), ElementId("d1"))
        client.show_async.assert_not_called()

    def test_update_rejects_structural_pages_field(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Patching ``pages`` on a legacy composite root defers to ``show``."""
        store = HubDisplay()
        _seed_legacy_group_with_child(store, group_id="grp", child_id="c1")
        client = _bind_store(monkeypatch, store)

        result = update(
            "s1",
            [{"id": "grp", "set": {"pages": [[{"kind": "text", "id": "p1"}]]}}],
        )

        assert result.startswith("error: scene not updated")
        assert "show" in result
        assert "pages" in result
        resolved = store.resolve(SceneId("s1"), ElementId("grp"))
        group = cast("LegacyGroupElement", resolved)
        assert group.pages == []
        with pytest.raises(UnknownElementError):
            store.resolve(SceneId("s1"), ElementId("p1"))
        client.show_async.assert_not_called()

    def test_update_mixed_abc_and_legacy_batch_both_land_one_repush(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An ABC patch and a legacy patch in one batch both land, re-pushed once.

        This is the central design claim: the write path above the seam is
        branch-free, so a mixed batch commits through one uniform loop and the Hub
        re-pushes the affected scene exactly once.
        """
        store = HubDisplay()
        header = CollapsingHeaderElement(id="hdr", label="Details", open=False)
        selectable = agent_element_factory().element_from_dict(
            {"kind": "selectable", "id": "sl1", "label": "opt", "selected": False}
        )
        store.replace_scene(
            ConnectionId("local"),
            SceneId("s1"),
            [cast("DomainElement", header), cast("DomainElement", selectable)],
        )
        client = _bind_store(monkeypatch, store)

        result = update(
            "s1",
            [
                {"id": "hdr", "set": {"open": True}},
                {"id": "sl1", "set": {"selected": True}},
            ],
        )

        assert result == "shown:s1"
        patched_header = store.resolve(SceneId("s1"), ElementId("hdr"))
        assert isinstance(patched_header, CollapsingHeaderElement)
        assert patched_header.open is True
        patched_selectable = store.resolve(SceneId("s1"), ElementId("sl1"))
        assert isinstance(patched_selectable, SelectableElement)
        assert patched_selectable.selected is True
        assert client.replicator.dirtied == [SceneId("s1")]

    def test_update_cross_connection_legacy_ownership_is_rejected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A legacy root seeded under one connection is not writable by another.

        Ownership is checked before the seam for legacy roots exactly as for ABC
        elements: connection ``other`` may neither patch nor remove ``local``'s
        selectable. The store is untouched and nothing is re-pushed.
        """
        store = HubDisplay()
        _seed_legacy_root(store, element_id="sl1", label="opt", connection="local")
        client = _bind_store(monkeypatch, store)

        token = _session_key.set("intruder")
        try:
            patched = update("s1", [{"id": "sl1", "set": {"label": "hacked"}}])
            removed = update("s1", [{"id": "sl1", "remove": True}])
        finally:
            _session_key.reset(token)

        assert patched.startswith("error: scene not updated")
        assert removed.startswith("error: scene not updated")
        spinner = store.resolve(SceneId("s1"), ElementId("sl1"))
        assert isinstance(spinner, SpinnerElement)
        assert spinner.label == "opt"
        client.show_async.assert_not_called()

    def test_update_batch_with_legacy_composite_rejection_is_atomic(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A batch with a legacy composite patch + one invalid patch commits none.

        The legacy composite root's ``replace`` never lands when a sibling patch
        fails validation — the composite keeps its title AND its children by
        reference, proving the atomicity boundary covers the legacy realization.
        """
        store = HubDisplay()
        child = _seed_legacy_window_with_child(store, window_id="w1", title="Old")
        hdr = CollapsingHeaderElement(id="hdr", label="Details", open=False)
        store.apply(
            ConnectionId("local"),
            AddElement(
                scene_id=SceneId("s1"),
                element=cast("DomainElement", hdr),
                parent_id=None,
            ),
        )
        client = _bind_store(monkeypatch, store)

        result = update(
            "s1",
            [
                {"id": "w1", "set": {"title": "New"}},
                {"id": "hdr", "set": {"label": ""}},
            ],
        )

        assert result.startswith("error: scene not updated")
        window = cast("WindowElement", store.resolve(SceneId("s1"), ElementId("w1")))
        assert window.title == "Old"
        assert window.children[0] is child
        client.show_async.assert_not_called()

    def test_update_commit_failure_restores_legacy_composite(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A commit-time raise after a legacy composite commit rolls it back exactly.

        The legacy composite root commits first (index rebound); a later ABC
        commit then raises. The writer restores the rebound root to its original
        frozen instance — title reverted, children identity intact — and the bug
        propagates rather than leaving a half-applied batch.
        """
        store = HubDisplay()
        child = _seed_legacy_window_with_child(store, window_id="w1", title="Old")
        hdr = CollapsingHeaderElement(id="hdr", label="Details", open=False)
        store.apply(
            ConnectionId("local"),
            AddElement(
                scene_id=SceneId("s1"),
                element=cast("DomainElement", hdr),
                parent_id=None,
            ),
        )
        _bind_store(monkeypatch, store)

        # Succeed on the rejection-phase copy, raise on the live commit — so the
        # legacy composite has already committed when the ABC commit fails.
        calls = {"n": 0}
        original_set_open = CollapsingHeaderElement._set_open

        def _flaky(self: CollapsingHeaderElement, value: object) -> None:
            calls["n"] += 1
            if calls["n"] >= 2:
                raise AttributeError("boom on live commit")
            original_set_open(self, value)

        monkeypatch.setattr(CollapsingHeaderElement, "_set_open", _flaky)

        with pytest.raises(AttributeError, match="boom on live commit"):
            update(
                "s1",
                [
                    {"id": "w1", "set": {"title": "New"}},
                    {"id": "hdr", "set": {"open": True}},
                ],
            )

        window = cast("WindowElement", store.resolve(SceneId("s1"), ElementId("w1")))
        assert window.title == "Old"
        assert window.children[0] is child

    def test_update_setter_bug_surfaces_as_bug(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An incidental bug inside a setter propagates, never laundered.

        The writer catches only the documented setter-refusal exceptions
        (``ValueError`` / ``TypeError``). A setter that raises ``AttributeError``
        is a real internal fault, so it surfaces rather than becoming an
        agent-facing "reason".
        """
        store = HubDisplay()
        _seed_store(store)
        _bind_store(monkeypatch, store)

        def _boom(self: object, value: object) -> None:
            raise AttributeError("internal setter fault")

        monkeypatch.setattr(CollapsingHeaderElement, "_set_open", _boom)

        with pytest.raises(AttributeError, match="internal setter fault"):
            update("s1", [{"id": "hdr", "set": {"open": True}}])


class TestClearTool:
    def test_clear_empties_hub_store_and_marks_cleared(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Clear empties the caller's authoritative scenes and signals a blank."""
        store = HubDisplay()
        _seed_store(store)
        client = _bind_store(monkeypatch, store)

        result = clear()

        assert result == "cleared"
        assert store.scene_roots(SceneId("s1")) == []
        assert store.elements_owned_by(ConnectionId("local")) == ()
        assert client.replicator.cleared == 1

    def test_clear_leaves_other_connections_scenes(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Clear empties only the caller's Hub scenes; another agent's survives."""
        store = HubDisplay()
        _seed_store(store, scene="s1", header_id="hdr")  # owned by "local"
        other = CollapsingHeaderElement(id="other", label="Other", open=False)
        store.replace_scene(
            ConnectionId("agent-b"),
            SceneId("s-other"),
            [cast("DomainElement", other)],
        )
        _bind_store(monkeypatch, store)

        result = clear()

        assert result == "cleared"
        assert store.scene_roots(SceneId("s1")) == []
        # agent-b's scene is untouched by local's clear.
        assert store.resolve(SceneId("s-other"), ElementId("other")).id == "other"

    def test_clear_empties_all_scenes_the_caller_owns(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A caller owning several scenes gets every one emptied."""
        store = HubDisplay()
        _seed_store(store, scene="s1", header_id="a")
        _seed_store(store, scene="s2", header_id="b", label="B")
        _bind_store(monkeypatch, store)

        result = clear()

        assert result == "cleared"
        assert store.scene_roots(SceneId("s1")) == []
        assert store.scene_roots(SceneId("s2")) == []
        assert store.elements_owned_by(ConnectionId("local")) == ()


class TestPingTool:
    @patch("punt_lux.tools.tools.time")
    @patch("punt_lux.domain.hub.clients.client_registry.get")
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

    @patch("punt_lux.domain.hub.clients.client_registry.get")
    @patch.object(DisplayPaths, "is_running", return_value=True)
    def test_ping_timeout(self, mock_running: MagicMock, mock_get: MagicMock) -> None:
        client = _mock_client()
        client.ping.return_value = None
        mock_get.return_value = client

        result = ping()
        assert result == "timeout"


class TestRecvTool:
    def test_recv_business_event(self, monkeypatch: pytest.MonkeyPatch) -> None:
        message = ObserverMessage(topic="work.saved", payload={"id": "save_btn"})

        def _queued(_connection_id: ConnectionId, _timeout: float) -> ObserverMessage:
            return message

        _bind_pubsub(monkeypatch, _queued)
        assert recv() == 'event:work.saved:{"id": "save_btn"}'

    def test_recv_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _empty(_connection_id: ConnectionId, _timeout: float) -> None:
            return None

        _bind_pubsub(monkeypatch, _empty)
        assert recv() == "none"


class TestDisplayModeTool:
    def test_display_mode_returns_on(self, tmp_path: Path) -> None:
        (tmp_path / ".punt-labs").mkdir()
        (tmp_path / ".punt-labs" / "lux.md").write_text(
            '---\ndisplay: "y"\n---\n', encoding="utf-8"
        )
        assert display_mode(repo=str(tmp_path)) == "display:on"

    def test_display_mode_returns_off_when_unset(self, tmp_path: Path) -> None:
        assert display_mode(repo=str(tmp_path)) == "display:off"


class TestSetDisplayModeTool:
    @patch("punt_lux.domain.hub.clients.client_registry.get")
    def test_set_display_mode_y(self, mock_get: MagicMock, tmp_path: Path) -> None:
        mock_get.return_value = _mock_client()
        assert set_display_mode("y", repo=str(tmp_path)) == "display:on"
        content = (tmp_path / ".punt-labs" / "lux.md").read_text()
        assert 'display: "y"' in content

    def test_set_display_mode_n(self, tmp_path: Path) -> None:
        assert set_display_mode("n", repo=str(tmp_path)) == "display:off"
        content = (tmp_path / ".punt-labs" / "lux.md").read_text()
        assert 'display: "n"' in content

    def test_set_display_mode_invalid(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="Invalid mode"):
            set_display_mode("bogus", repo=str(tmp_path))


class TestDisplayModeRepoArg:
    def test_set_then_read_roundtrip_in_repo(self, tmp_path: Path) -> None:
        with patch(
            "punt_lux.domain.hub.clients.client_registry.get",
            return_value=_mock_client(),
        ):
            assert set_display_mode("y", repo=str(tmp_path)) == "display:on"
        assert (tmp_path / ".punt-labs" / "lux.md").exists()
        assert display_mode(repo=str(tmp_path)) == "display:on"

        with patch(
            "punt_lux.domain.hub.clients.client_registry.get",
            return_value=_mock_client(),
        ):
            assert set_display_mode("n", repo=str(tmp_path)) == "display:off"
        assert display_mode(repo=str(tmp_path)) == "display:off"

    def test_repo_paths_are_isolated(self, tmp_path: Path) -> None:
        repo_a = tmp_path / "a"
        repo_b = tmp_path / "b"
        repo_a.mkdir()
        repo_b.mkdir()
        with patch(
            "punt_lux.domain.hub.clients.client_registry.get",
            return_value=_mock_client(),
        ):
            set_display_mode("y", repo=str(repo_a))
        set_display_mode("n", repo=str(repo_b))
        assert display_mode(repo=str(repo_a)) == "display:on"
        assert display_mode(repo=str(repo_b)) == "display:off"

    def test_repo_must_be_absolute(self) -> None:
        with pytest.raises(ValueError, match="absolute path"):
            display_mode(repo="relative/path")

    def test_repo_must_exist(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="does not exist"):
            display_mode(repo=str(tmp_path / "does-not-exist"))

    def test_repo_must_be_directory(self, tmp_path: Path) -> None:
        file_path = tmp_path / "regular-file"
        file_path.write_text("not a directory")
        with pytest.raises(ValueError, match="must be a directory"):
            display_mode(repo=str(file_path))

    def test_repo_empty_string_raises(self) -> None:
        with pytest.raises(ValueError, match="repo is required"):
            display_mode(repo="")

    def test_repo_is_required(self) -> None:
        with pytest.raises(TypeError):
            display_mode()  # type: ignore[call-arg]


class TestClearIsDisplayIndependent:
    """Clear never checks or contacts the display — the store is the authority.

    Emptying the store must not hinge on the display being up. Clear always
    empties the caller's scenes, signals the replicator, and returns "cleared";
    the replicator alone deals with the display in the background.
    """

    @patch("punt_lux.domain.hub.clients.client_registry.get")
    def test_clear_never_probes_or_reaches_the_display(
        self, mock_get: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store = HubDisplay()
        _seed_store(store)
        _bind_store(monkeypatch, store)

        result = clear()

        assert result == "cleared"
        # The tool thread never opens a connection to the display.
        mock_get.assert_not_called()

    def test_clear_empties_the_store_and_signals_a_blank(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store = HubDisplay()
        _seed_store(store)
        client = _bind_store(monkeypatch, store)

        result = clear()

        assert result == "cleared"
        assert store.scene_roots(SceneId("s1")) == []
        assert store.elements_owned_by(ConnectionId("local")) == ()
        assert client.replicator.cleared == 1

    @patch("punt_lux.domain.hub.clients.client_registry.get")
    def test_clear_returns_cleared_even_with_an_empty_store(
        self, mock_get: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # An empty store has nothing to clear, but the tool still returns cleared
        # and never contacts the display.
        _bind_store(monkeypatch, HubDisplay())

        result = clear()

        assert result == "cleared"
        mock_get.assert_not_called()


class TestPingNoAutoSpawn:
    @patch("punt_lux.domain.hub.clients.client_registry.get")
    @patch.object(DisplayPaths, "is_running", return_value=False)
    def test_ping_not_running(
        self, mock_running: MagicMock, mock_get: MagicMock
    ) -> None:

        result = ping()
        assert result == "not running"
        mock_get.assert_not_called()

    @patch("punt_lux.tools.tools.time")
    @patch("punt_lux.domain.hub.clients.client_registry.get")
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
    """inspect_scene reads the authoritative Hub store, not the display."""

    def test_inspect_scene_returns_the_hub_tree(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store = HubDisplay()
        _seed_group_with_child(store, scene="s1", group_id="g1", child_id="t1")
        _bind_store(monkeypatch, store)

        result = inspect_scene("s1")
        assert isinstance(result, SceneInspection)
        assert result.scene_id == "s1"
        assert result.elements[0].id == "g1"
        assert result.elements[0].children[0].id == "t1"

    def test_inspect_scene_unknown_scene_is_not_found(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _bind_store(monkeypatch, HubDisplay())
        result = inspect_scene("missing")
        assert isinstance(result, OpError)
        assert result.code == "not_found"


class TestListScenesTool:
    """list_scenes reads the authoritative Hub store, not the display."""

    def test_list_scenes_returns_the_hub_scenes(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store = HubDisplay()
        _seed_group_with_child(store, scene="s1", group_id="g1", child_id="t1")
        _bind_store(monkeypatch, store)

        result = list_scenes()
        assert isinstance(result, SceneList)
        assert any(s.scene_id == "s1" for s in result.scenes)

    def test_list_scenes_empty_store(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _bind_store(monkeypatch, HubDisplay())
        result = list_scenes()
        assert isinstance(result, SceneList)
        assert result.scenes == []
        assert result.frames == []


class TestScreenshotTool:
    @patch("punt_lux.domain.hub.clients.client_registry.get")
    @patch.object(DisplayPaths, "is_running", return_value=False)
    def test_screenshot_not_running(
        self, mock_running: MagicMock, mock_get: MagicMock
    ) -> None:

        result = screenshot()
        assert result == "not running"
        mock_get.assert_not_called()

    @patch("punt_lux.domain.hub.clients.client_registry.get")
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

    @patch("punt_lux.domain.hub.clients.client_registry.get")
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

    @patch("punt_lux.domain.hub.clients.client_registry.get")
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


def _has_registered_item(items: list[dict[str, object]], item_id: str) -> bool:
    """Whether the registry's flat tool-item list carries ``item_id``."""
    return any(item.get("id") == item_id for item in items)


class TestCleanupSession:
    def test_drops_the_sessions_menu_items(self) -> None:
        from punt_lux.domain.hub.menu_registry import hub_menu_registry

        conn = ConnectionId("sess-1")
        hub_menu_registry.register_item(conn, {"label": "Run", "id": "cleanup-tool"})
        _cleanup_session("sess-1")
        assert not _has_registered_item(
            hub_menu_registry.registered_items(), "cleanup-tool"
        )

    def test_noop_when_no_items(self) -> None:
        _cleanup_session("nonexistent-session")  # must not raise


class TestRegisterToolSessionTracking:
    def test_registers_the_item_in_the_hub_registry(self) -> None:
        from punt_lux.domain.hub.menu_registry import hub_menu_registry

        conn = ConnectionId("local")
        hub_menu_registry.drop(conn)
        try:
            assert (
                register_tool(label="Run", tool_id="track-run")
                == "registered:track-run"
            )
            assert _has_registered_item(
                hub_menu_registry.registered_items(), "track-run"
            )
        finally:
            hub_menu_registry.drop(conn)

    def test_registers_under_custom_session_key(self) -> None:
        from punt_lux.domain.hub.menu_registry import hub_menu_registry

        conn = ConnectionId("ws-99")
        token = _session_key.set("ws-99")
        try:
            register_tool(label="Build", tool_id="track-build")
            assert _has_registered_item(
                hub_menu_registry.registered_items(), "track-build"
            )
        finally:
            _session_key.reset(token)
            hub_menu_registry.drop(conn)
