"""Lux MCP server — expose display tools to AI agents.

Provides FastMCP tools: ``show``, ``show_table``, ``show_dashboard``,
``update``, ``clear``, ``ping``, and ``recv``.
Uses :class:`LuxClient` under the hood with lazy connection on first call.

Run via stdio transport::

    lux serve
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

from fastmcp import FastMCP

from punt_lux.client import LuxClient
from punt_lux.protocol import (
    InteractionMessage,
    Patch,
    element_from_dict,
)

logger = logging.getLogger(__name__)

mcp = FastMCP(
    "lux",
    instructions=(
        "Lux is a visual output surface. Use these tools to display "
        "text, images, buttons, separators, and interactive elements "
        "(sliders, checkboxes, combos, text inputs, radio buttons, "
        "color pickers) in a window the user can see.\n\n"
        "All lux tool output is pre-formatted plain text using unicode "
        "characters for alignment. Always emit lux output verbatim — "
        "never reformat, never convert to markdown tables, never wrap "
        "in code fences or boxes.\n\n"
        "Layout best practices:\n"
        "- Use group with layout='columns' for side-by-side elements\n"
        "- Use tab_bar to organize multi-view interfaces\n"
        "- Use collapsing_header for progressive disclosure\n"
        "- Use window for floating panels (inspector, detail views)\n"
        "- Nest containers freely: groups inside tabs, windows inside groups\n\n"
        "Common patterns:\n"
        "- Data explorer: use show_table() for filterable tables with detail\n"
        "- Dashboard: use show_dashboard() for metrics + charts + table\n"
        "- Form: input_text + combo + checkbox + button for submission\n"
        "- Custom layout: use show() to compose any element tree"
    ),
)

_client: LuxClient | None = None


def _get_client() -> LuxClient:
    """Return a connected LuxClient, creating one if needed."""
    global _client
    if _client is None or not _client.is_connected:
        _client = LuxClient()
        _client.connect()
    return _client


def _with_reconnect[T](fn: Callable[[], T]) -> T:
    """Run *fn* with one automatic reconnect on broken pipe.

    If the display server restarts, the cached socket dies silently —
    ``is_connected`` still returns True because the socket object exists.
    This wrapper catches the resulting ``OSError`` (including
    ``BrokenPipeError``), tears down the stale client, connects a fresh
    one, and retries *fn* exactly once.
    """
    global _client
    try:
        return fn()
    except OSError:
        logger.info("Connection lost, reconnecting to display")
        if _client is not None:
            _client.close()
            _client = None
        return fn()


@mcp.tool()
def show(
    scene_id: str,
    elements: list[dict[str, Any]],
    title: str | None = None,
    layout: str = "single",
) -> str:
    """Display a scene in the Lux window.

    Replaces the current window contents with the given elements.
    Each element is a dict with a ``kind`` field (defaults to "text").

    Display elements:
      Text:         {"kind": "text", "id": "t1", "content": "Hello"}
      Button:       {"kind": "button", "id": "b1", "label": "Click me"}
      Image:        {"kind": "image", "id": "i1", "path": "/path/to/img.png"}
      Separator:    {"kind": "separator"}

    Interactive elements (generate "changed" events via recv):
      Slider:       {"kind": "slider", "id": "sl1", "label": "Vol"}
      Checkbox:     {"kind": "checkbox", "id": "cb1", "label": "On"}
      Combo:        {"kind": "combo", "id": "co1", "items": ["A","B"]}
      Input text:   {"kind": "input_text", "id": "it1", "label": "Name"}
      Radio:        {"kind": "radio", "id": "r1", "items": ["A","B"]}
      Color picker: {"kind": "color_picker", "id": "cp1", "label": "Bg"}

    List elements:
      Selectable:   {"kind": "selectable", "id": "s1", "label": "Item"}
      Tree:         {"kind": "tree", "id": "tr1", "label": "Files",
                     "nodes": [{"label": "src", "children": [
                       {"label": "main.py"}]}]}

    Data elements:
      Table:        {"kind": "table", "id": "tbl1",
                     "columns": ["Name", "Score"],
                     "rows": [["Alice", 95], ["Bob", 87]],
                     "flags": ["borders", "row_bg"]}
      Plot:         {"kind": "plot", "id": "p1", "title": "Trend",
                     "x_label": "Time", "y_label": "Value",
                     "series": [{"label": "y", "type": "line",
                       "x": [1,2,3], "y": [10,20,15]}]}

    Status elements:
      Progress:     {"kind": "progress", "id": "pg1", "fraction": 0.73}
      Spinner:      {"kind": "spinner", "id": "sp1", "label": "Loading..."}

    Rich text:
      Markdown:     {"kind": "markdown", "id": "md1",
                     "content": "# Title\\n\\nBold **text**."}

    Canvas element:
      Draw:         {"kind": "draw", "id": "d1", "commands": [...]}

    Code-on-demand (shows consent dialog, then runs each frame):
      Render fn:    {"kind": "render_function", "id": "rf1",
                     "source": "def render(ctx):\\n    ..."}

    Layout containers (nest other elements as children):
      Group:        {"kind": "group", "id": "g1", "layout": "columns",
                     "children": [{"kind": "text", ...}, ...]}
      Tab bar:      {"kind": "tab_bar", "id": "tb1",
                     "tabs": [{"label": "Tab 1", "children": [...]}, ...]}
      Collapsing:   {"kind": "collapsing_header", "id": "ch1",
                     "label": "Details", "default_open": true,
                     "children": [...]}
      Window:       {"kind": "window", "id": "w1", "title": "Panel",
                     "x": 50, "y": 50, "width": 300, "height": 200,
                     "children": [...]}

    All elements with an id support an optional ``"tooltip"`` field
    (string shown on hover).

    Returns ``"ack:<scene_id>"`` on success or ``"timeout"`` if the
    display doesn't respond.
    """
    typed_elements = [element_from_dict(e) for e in elements]

    def _call() -> str:
        client = _get_client()
        ack = client.show(scene_id, typed_elements, title=title, layout=layout)
        if ack is None:
            return "timeout"
        return f"ack:{ack.scene_id}"

    return _with_reconnect(_call)


@mcp.tool()
def show_table(
    scene_id: str,
    columns: list[str],
    rows: list[list[Any]],
    filters: list[dict[str, Any]] | None = None,
    detail: dict[str, Any] | None = None,
    flags: list[str] | None = None,
    title: str | None = None,
) -> str:
    """Display a filterable data table with optional detail panel.

    This is a convenience wrapper around ``show()`` for the most common
    pattern: a searchable, filterable table with drill-down detail.
    Filters and detail run at 60fps in the display — zero round trips.

    Args:
        scene_id: Unique identifier for this scene.
        columns: Column headers (e.g., ["ID", "Title", "Status"]).
        rows: Table data — each row is a list matching columns order.
        filters: Built-in filter controls rendered above the table.
            Two types:
              Search:  {"type": "search", "column": [0, 1],
                        "hint": "Filter by ID or title..."}
              Combo:   {"type": "combo", "column": 2, "label": "Status",
                        "items": ["All", "Open", "Closed"]}
            First combo item should be "All" (no filter). Include only
            values that exist in the data. 1-3 filters is ideal.
        detail: Drill-down panel shown when a row is selected.
            Structure:
              {"fields": ["ID", "Status", "Priority"],
               "rows": [["ISS-1", "Open", "P1"], ...],
               "body": ["Full description for row 1...", ...]}
            ``detail.rows`` must be parallel to ``rows`` (same count,
            same order). ``detail.body`` is the expanded text per row.
        flags: Table flags (default: ["borders", "row_bg"]).
        title: Window title.

    Example — issue explorer with search, status filter, and detail::

        show_table(
            scene_id="issues",
            columns=["ID", "Title", "Status", "Priority"],
            rows=[
                ["ISS-1", "Fix login timeout", "Open", "P1"],
                ["ISS-2", "Add dark mode", "In Progress", "P2"],
            ],
            filters=[
                {"type": "search", "column": [0, 1],
                 "hint": "Filter by ID or title..."},
                {"type": "combo", "column": 2, "label": "Status",
                 "items": ["All", "Open", "In Progress"]},
            ],
            detail={
                "fields": ["ID", "Status", "Priority", "Assignee"],
                "rows": [
                    ["ISS-1", "Open", "P1", "alice"],
                    ["ISS-2", "In Progress", "P2", "bob"],
                ],
                "body": [
                    "Login flow times out after 30s on slow connections.",
                    "Add system-wide dark mode toggle.",
                ],
            },
            title="Issue Explorer",
        )
    """
    table: dict[str, Any] = {
        "kind": "table",
        "id": "table",
        "columns": columns,
        "rows": rows,
        "flags": flags or ["borders", "row_bg"],
    }
    if filters is not None:
        table["filters"] = filters
    if detail is not None:
        table["detail"] = detail
    return show(scene_id, [table], title=title)


@mcp.tool()
def show_dashboard(
    scene_id: str,
    metrics: list[dict[str, str]] | None = None,
    charts: list[dict[str, Any]] | None = None,
    table_columns: list[str] | None = None,
    table_rows: list[list[Any]] | None = None,
    title: str | None = None,
) -> str:
    """Display a dashboard with metric cards, charts, and a data table.

    This is a convenience wrapper around ``show()`` for the dashboard
    pattern: metric cards across the top, charts in the middle, and a
    summary table at the bottom. All sections are optional — include
    only the ones relevant to your data.

    Args:
        scene_id: Unique identifier for this scene.
        metrics: Key-value metric cards displayed in a row.
            Each dict: {"label": "Total Users", "value": "1,234"}.
            2-5 cards is ideal for a single-glance overview.
        charts: Plot elements displayed below the metrics.
            Each dict is a plot config:
              {"id": "p1", "title": "Trend",
               "x_label": "Time", "y_label": "Value",
               "series": [{"label": "requests", "type": "line",
                           "x": [1,2,3], "y": [10,20,15]}]}
            Series types: "line" (trends), "bar" (comparisons),
            "scatter" (correlations).
        table_columns: Column headers for the summary table.
        table_rows: Rows for the summary table.
        title: Window title.

    Example — test results dashboard::

        show_dashboard(
            scene_id="test-results",
            metrics=[
                {"label": "Total", "value": "142"},
                {"label": "Passed", "value": "137"},
                {"label": "Failed", "value": "5"},
                {"label": "Duration", "value": "2m 34s"},
            ],
            charts=[{
                "id": "duration-chart",
                "title": "Test Duration by Suite",
                "x_label": "Suite", "y_label": "Seconds",
                "series": [{"label": "duration", "type": "bar",
                            "x": [1, 2, 3],
                            "y": [45, 82, 27]}],
            }],
            table_columns=["Test", "Status", "Duration"],
            table_rows=[
                ["test_login", "PASS", "1.2s"],
                ["test_upload", "FAIL", "5.0s"],
            ],
            title="Test Results",
        )
    """
    elements: list[dict[str, Any]] = []

    if metrics:
        cards = [
            {
                "kind": "group",
                "id": f"metric-{i}",
                "children": [
                    {"kind": "text", "id": f"metric-label-{i}", "content": m["label"]},
                    {
                        "kind": "text",
                        "id": f"metric-value-{i}",
                        "content": m["value"],
                        "style": "heading",
                    },
                ],
            }
            for i, m in enumerate(metrics)
        ]
        elements.append(
            {
                "kind": "group",
                "id": "metrics-row",
                "layout": "columns",
                "children": cards,
            }
        )
        elements.append({"kind": "separator"})

    if charts:
        for chart in charts:
            plot: dict[str, Any] = {"kind": "plot", **chart}
            if "id" not in plot:
                plot["id"] = f"chart-{len(elements)}"
            elements.append(plot)
        elements.append({"kind": "separator"})

    if table_columns and table_rows:
        elements.append(
            {
                "kind": "table",
                "id": "dashboard-table",
                "columns": table_columns,
                "rows": table_rows,
                "flags": ["borders", "row_bg"],
            }
        )

    return show(scene_id, elements, title=title)


@mcp.tool()
def update(
    scene_id: str,
    patches: list[dict[str, Any]],
) -> str:
    """Update elements in the current scene without replacing everything.

    Each patch targets an element by id and can set fields or remove it:
      {"id": "t1", "set": {"content": "Updated text"}}
      {"id": "b1", "remove": True}

    Returns ``"ack:<scene_id>"`` on success or ``"timeout"`` if the
    display doesn't respond.
    """
    typed_patches = [
        Patch(
            id=p["id"],
            set=p.get("set"),
            remove=p.get("remove", False),
            insert_after=p.get("insert_after"),
        )
        for p in patches
    ]

    def _call() -> str:
        client = _get_client()
        ack = client.update(scene_id, typed_patches)
        if ack is None:
            return "timeout"
        return f"ack:{ack.scene_id}"

    return _with_reconnect(_call)


@mcp.tool()
def set_menu(menus: list[dict[str, Any]]) -> str:
    """Add custom menus to the Lux display menu bar.

    Each menu: {"label": "Tools", "items": [
        {"label": "Run", "id": "run_btn"},
        {"label": "---"},  # separator
    ]}

    Menu item clicks generate interaction events via recv().
    """

    def _call() -> str:
        client = _get_client()
        client.set_menu(menus)
        return "ok"

    return _with_reconnect(_call)


@mcp.tool()
def set_theme(theme: str) -> str:
    """Set the Lux display theme.

    Available themes (snake_case names):
      imgui_colors_light, imgui_colors_dark, imgui_colors_classic,
      darcula, darcula_darker, material_flat, photoshop_style,
      grey_flat, cherry, light_rounded, microsoft_style, from_imgui_colors_dark

    Example: set_theme("imgui_colors_light") for dashboards and data views.
    """

    def _call() -> str:
        client = _get_client()
        client.set_theme(theme)
        return f"theme:{theme}"

    return _with_reconnect(_call)


@mcp.tool()
def clear() -> str:
    """Clear the Lux display window. Removes all content."""

    def _call() -> str:
        client = _get_client()
        client.clear()
        return "cleared"

    return _with_reconnect(_call)


@mcp.tool()
def ping() -> str:
    """Ping the display server. Returns round-trip time or "timeout"."""

    def _call() -> str:
        client = _get_client()
        pong = client.ping()
        if pong is None:
            return "timeout"
        if pong.ts is not None:
            rtt = time.time() - pong.ts
            return f"pong:rtt={rtt:.3f}s"
        return "pong"

    return _with_reconnect(_call)


@mcp.tool()
def recv(timeout: float = 1.0) -> str:
    """Receive the next event from the display (e.g., button clicks).

    Returns a description of the event or "none" if no event within timeout.
    """

    def _call() -> str:
        client = _get_client()
        msg = client.recv(timeout=timeout)
        if msg is None:
            return "none"
        if isinstance(msg, InteractionMessage):
            return (
                f"interaction:element={msg.element_id},"
                f"action={msg.action},value={msg.value}"
            )
        return f"event:{type(msg).__name__}"

    return _with_reconnect(_call)
