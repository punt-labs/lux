"""Lux MCP server — expose display tools to AI agents.

Provides FastMCP tools: ``show``, ``show_table``, ``show_dashboard``,
``show_diagram``, ``update``, ``clear``, ``ping``, and ``recv``.
Uses :class:`LuxClient` under the hood with lazy connection on first call.

Run via stdio transport::

    lux serve
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import math
import threading
import time
from collections.abc import AsyncIterator, Callable
from typing import Any, Literal, cast

from fastmcp import FastMCP

from punt_lux.apps.beads import render_beads_board
from punt_lux.client import LuxClient
from punt_lux.config import read_config, resolve_config_path, write_field
from punt_lux.protocol import (
    InteractionMessage,
    Patch,
    element_from_dict,
)

logger = logging.getLogger(__name__)


@contextlib.asynccontextmanager
async def _lifespan(_server: FastMCP) -> AsyncIterator[None]:
    """Eager-connect to the display server when display=y.

    Runs ``_get_client()`` in a thread so the blocking socket connect
    and potential ``ensure_display()`` auto-spawn don't stall the
    async event loop.
    """
    config_path = resolve_config_path()
    try:
        cfg = read_config(config_path)
    except (OSError, ValueError) as exc:
        logger.warning("Failed to read display config (%s): %s", config_path, exc)
        yield
        return

    if cfg.display == "y":
        try:
            logger.info("display=y, eagerly connecting to display server")
            await asyncio.to_thread(_get_client)
        except (RuntimeError, OSError, ValueError, KeyError):
            logger.warning(
                "Eager connect to display failed; will connect on first tool call",
                exc_info=True,
            )
    yield


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
        "- Architecture diagram: use show_diagram() for boxes + arrows + labels\n"
        "- Form: input_text + combo + checkbox + button for submission\n"
        "- Custom layout: use show() to compose any element tree"
    ),
    lifespan=_lifespan,
)

_client: LuxClient | None = None
_client_lock = threading.RLock()


def _on_beads_browser(_msg: InteractionMessage) -> None:
    """Callback: open the Beads Browser in a frame."""
    if _client is None:
        logger.warning("_on_beads_browser: client is None, ignoring menu click")
        return
    render_beads_board(_client)


_apps_registered_for: int | None = None


def _setup_apps(client: LuxClient) -> None:
    """Declare built-in application menu items and callbacks.

    Idempotent per client identity — safe to call on every
    ``_get_client()`` invocation.  Re-registers if the client
    instance changes (e.g. after recreation).
    """
    global _apps_registered_for
    if _apps_registered_for == id(client):
        return
    client.declare_menu_item({"id": "app-beads", "label": "Beads Browser"})
    client.on_event("app-beads", "menu", _on_beads_browser)
    _apps_registered_for = id(client)


def _get_client() -> LuxClient:
    """Return a connected LuxClient, creating or reconnecting as needed.

    Thread-safe: holds ``_client_lock`` to prevent duplicate creation
    when called concurrently from the lifespan thread and MCP tool threads.
    """
    global _client
    with _client_lock:
        if _client is None:
            _client = LuxClient(name="lux-mcp")
        _setup_apps(_client)
        if not _client.is_connected:
            _client.connect()
        if not _client.listener_active:
            _client.start_listener()
        return _client


def _with_reconnect[T](fn: Callable[[], T]) -> T:
    """Run *fn* with one automatic reconnect on socket failure.

    If the display server restarts, the cached socket dies silently —
    ``is_connected`` still returns True because the socket object exists.
    This wrapper catches ``OSError`` (covers broken pipe, connection
    reset, bad file descriptor, etc.), closes the stale socket,
    reconnects the same client instance (preserving accumulated state
    like registered menu items), and retries *fn* exactly once.

    Holds ``_client_lock`` during the close/reconnect sequence to
    prevent races with ``_get_client()`` in other threads.
    """
    global _client
    try:
        return fn()
    except OSError as exc:
        logger.info("Connection lost (%s), reconnecting to display", type(exc).__name__)
        with _client_lock:
            if _client is not None:
                _client.close()
                try:
                    _client.connect()
                except (OSError, RuntimeError) as reconnect_exc:
                    msg = f"Reconnect failed after connection loss: {reconnect_exc}"
                    raise RuntimeError(msg) from exc
            return fn()


@mcp.tool()
def show(
    scene_id: str,
    elements: list[dict[str, Any]],
    title: str | None = None,
    layout: str = "single",
    frame_id: str | None = None,
    frame_title: str | None = None,
    frame_size: list[int] | None = None,
    frame_flags: dict[str, bool] | None = None,
    frame_layout: str | None = None,  # "tab" or "stack"
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
      Paged group:  {"kind": "group", "id": "g2", "layout": "paged",
                     "children": [{"kind": "combo", "id": "nav", ...}],
                     "pages": [[{"kind": "text", ...}], ...],
                     "page_source": "nav"}
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

    Frame sizing (only with ``frame_id``):
      frame_size:  [width, height] in pixels — initial size hint (first use only).
      frame_flags: ImGui window flags. Supported keys:
        no_resize    — prevent user resizing
        no_collapse  — hide the collapse button
        auto_resize  — shrink-wrap to content each frame
      frame_layout: How multiple scenes in the same frame are arranged.
        "tab"   — one scene visible at a time via tab bar (default)
        "stack" — all scenes stacked vertically with collapsing headers

    Returns ``"ack:<scene_id>"`` on success or ``"timeout"`` if the
    display doesn't respond.
    """
    typed_elements = [element_from_dict(e) for e in elements]
    size_tuple: tuple[int, int] | None = None
    if frame_size is not None:
        if len(frame_size) != 2:
            return "error: frame_size must be [width, height]"
        size_tuple = (frame_size[0], frame_size[1])
    if frame_layout is not None and frame_layout not in ("tab", "stack"):
        return f"error: frame_layout must be 'tab' or 'stack', got {frame_layout!r}"
    validated_layout: Literal["tab", "stack"] | None = (
        cast("Literal['tab', 'stack']", frame_layout) if frame_layout else None
    )

    def _call() -> str:
        client = _get_client()
        ack = client.show(
            scene_id,
            typed_elements,
            title=title,
            layout=layout,
            frame_id=frame_id,
            frame_title=frame_title,
            frame_size=size_tuple,
            frame_flags=frame_flags,
            frame_layout=validated_layout,
        )
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
            ``detail.rows`` **and** ``detail.body`` must both be
            parallel to ``rows`` (same count, same order). Each
            entry in ``detail.body`` is the expanded text for the
            corresponding row.
        flags: Table flags (default: ["borders", "row_bg"]).
            Available: "borders", "row_bg", "resizable", "sortable",
            "copy_id" (copy first column to clipboard on row select).
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
        "flags": flags if flags is not None else ["borders", "row_bg"],
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

    sections: list[list[dict[str, Any]]] = []

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
        sections.append(
            [
                {
                    "kind": "group",
                    "id": "metrics-row",
                    "layout": "columns",
                    "children": cards,
                }
            ]
        )

    if charts:
        chart_elements: list[dict[str, Any]] = []
        for i, chart in enumerate(charts):
            plot: dict[str, Any] = {**chart, "kind": "plot"}
            if "id" not in plot:
                plot["id"] = f"chart-{i}"
            chart_elements.append(plot)
        sections.append(chart_elements)

    if table_columns is not None:
        sections.append(
            [
                {
                    "kind": "table",
                    "id": "dashboard-table",
                    "columns": table_columns,
                    "rows": table_rows if table_rows is not None else [],
                    "flags": ["borders", "row_bg"],
                }
            ]
        )

    for i, section in enumerate(sections):
        elements.extend(section)
        if i < len(sections) - 1:
            elements.append({"kind": "separator"})

    return show(scene_id, elements, title=title)


# -- diagram layout engine ---------------------------------------------------

# Layer color palette: (fill, border) pairs cycling per layer.
_LAYER_COLORS = [
    ("#2a4a6a", "#4488bb"),  # blue
    ("#3a2a1a", "#cc8833"),  # orange
    ("#1a3a2a", "#33aa77"),  # green
    ("#3a1a1a", "#cc5533"),  # red
    ("#2a1a3a", "#8855cc"),  # purple
    ("#1a2a3a", "#3388cc"),  # teal
]

_CHAR_W = 8  # estimated pixels per character in ImGui default font
_CHAR_H = 16  # estimated line height
_PAD_X = 24  # horizontal padding inside boxes
_PAD_Y = 16  # vertical padding inside boxes
_MARGIN = 40  # safe margin around entire canvas
_LAYER_GAP = 70  # vertical gap between layers
_NODE_GAP = 60  # horizontal gap between nodes
_LAYER_LABEL_W = 80  # reserved width for layer labels on the left


def _text_width(text: str) -> float:
    return len(text) * _CHAR_W


# Position tuple: (x, y, width, height) for each node.
_Pos = tuple[float, float, float, float]


def _measure_nodes(
    layers: list[dict[str, Any]],
) -> dict[str, tuple[float, float]]:
    """Return {node_id: (width, height)} for all nodes.

    Raises ValueError if duplicate node IDs are found.
    """
    sizes: dict[str, tuple[float, float]] = {}
    for layer in layers:
        for node in layer.get("nodes", []):
            nid = node["id"]
            if nid in sizes:
                msg = f"duplicate node id: {nid!r}"
                raise ValueError(msg)
            label = node.get("label", nid)
            detail = node.get("detail", "")
            tw = max(_text_width(label), _text_width(detail))
            w = tw + _PAD_X * 2
            h = _CHAR_H + _PAD_Y * 2 + (_CHAR_H if detail else 0)
            sizes[nid] = (w, h)
    return sizes


def _position_layers(
    layers: list[dict[str, Any]],
    sizes: dict[str, tuple[float, float]],
) -> tuple[dict[str, _Pos], list[tuple[float, float]], int, int]:
    """Assign (x, y, w, h) to each node, top-down by layer.

    Returns (positions, layer_y_bands, canvas_w, canvas_h).
    """
    positions: dict[str, _Pos] = {}
    bands: list[tuple[float, float]] = []
    y: float = _MARGIN
    max_w: float = 0

    # Dynamic label column: use max layer label width, minimum _LAYER_LABEL_W.
    # Only measure labels for layers that have nodes (empty layers are skipped
    # by _draw_nodes, so their labels never render).
    label_w: float = _LAYER_LABEL_W
    for layer in layers:
        if not layer.get("nodes"):
            continue
        raw_label = layer.get("label")
        if not raw_label:
            continue
        label_w = max(label_w, _text_width(str(raw_label)) + _PAD_X)

    # First pass: compute row widths to find max canvas width.
    content_x = _MARGIN + label_w
    row_widths: list[float] = []
    for layer in layers:
        nodes = layer.get("nodes", [])
        if not nodes:
            continue
        rw = sum(sizes[n["id"]][0] for n in nodes) + _NODE_GAP * (len(nodes) - 1)
        row_widths.append(rw)
        max_w = max(max_w, content_x + rw + _MARGIN)

    # Second pass: center each row within the canvas and assign positions.
    row_idx = 0
    for layer in layers:
        nodes = layer.get("nodes", [])
        if not nodes:
            continue
        row_h = max(sizes[n["id"]][1] for n in nodes)
        bands.append((y, y + row_h))
        rw = row_widths[row_idx]
        row_idx += 1
        # Center the row content within the available width.
        x: float = content_x + (max_w - content_x - _MARGIN - rw) / 2
        for node in nodes:
            nid = node["id"]
            nw, nh = sizes[nid]
            positions[nid] = (x, y + (row_h - nh) / 2, nw, nh)
            x += nw + _NODE_GAP
        y += row_h + _LAYER_GAP

    canvas_w = int(max_w) if max_w > 0 else _MARGIN * 2
    canvas_h = int(y - _LAYER_GAP + _MARGIN) if bands else _MARGIN * 2
    return positions, bands, canvas_w, canvas_h


def _draw_nodes(
    layers: list[dict[str, Any]],
    positions: dict[str, _Pos],
    bands: list[tuple[float, float]],
) -> list[dict[str, Any]]:
    """Emit draw commands for layer labels and node boxes."""
    cmds: list[dict[str, Any]] = []
    band_idx = 0
    for li, layer in enumerate(layers):
        nodes = layer.get("nodes", [])
        if not nodes:
            continue
        fill, border = _LAYER_COLORS[li % len(_LAYER_COLORS)]
        label = layer.get("label", "")
        ly_start, ly_end = bands[band_idx]
        band_idx += 1
        if label:
            mid_y = ly_start + (ly_end - ly_start) / 2 - _CHAR_H / 2
            cmds.append(
                {
                    "cmd": "text",
                    "pos": [_MARGIN, mid_y],
                    "text": label,
                    "color": "#666666",
                }
            )
        for node in nodes:
            cmds.extend(_draw_one_node(node, positions, fill, border))
    return cmds


def _draw_one_node(
    node: dict[str, Any],
    positions: dict[str, _Pos],
    fill: str,
    border: str,
) -> list[dict[str, Any]]:
    """Emit draw commands for a single node box with label and detail."""
    nid = node["id"]
    nx, ny, nw, nh = positions[nid]
    label = node.get("label", nid)
    detail = node.get("detail", "")
    cmds: list[dict[str, Any]] = [
        {
            "cmd": "rect",
            "min": [nx, ny],
            "max": [nx + nw, ny + nh],
            "rounding": 6,
            "filled": True,
            "color": fill,
        },
        {
            "cmd": "rect",
            "min": [nx, ny],
            "max": [nx + nw, ny + nh],
            "rounding": 6,
            "color": border,
        },
        {
            "cmd": "text",
            "pos": [nx + (nw - _text_width(label)) / 2, ny + _PAD_Y],
            "text": label,
            "color": border,
        },
    ]
    if detail:
        cmds.append(
            {
                "cmd": "text",
                "pos": [
                    nx + (nw - _text_width(detail)) / 2,
                    ny + _PAD_Y + _CHAR_H,
                ],
                "text": detail,
                "color": "#999999",
            }
        )
    return cmds


_PORT_INSET = 0.2  # fraction of node width reserved as inset on each side


def _spread_ports(
    edges_by_node: dict[str, list[dict[str, Any]]],
    positions: dict[str, _Pos],
    key_field: str,
) -> dict[int, float]:
    """Spread edge connection points across a node edge.

    ``key_field`` is the edge field pointing to the *opposite* node
    (``"to"`` for outgoing, ``"from"`` for incoming), used to sort
    ports left-to-right by the other endpoint's x-centre.

    Returns ``{edge_index: x_position}`` keyed by ``_idx`` so parallel
    edges between the same pair of nodes get distinct ports.
    """
    ports: dict[int, float] = {}
    for _nid, edges in edges_by_node.items():
        edges.sort(
            key=lambda e: positions[e[key_field]][0] + positions[e[key_field]][2] / 2,
        )
        nx, _ny, nw, _nh = positions[_nid]
        inset = nw * _PORT_INSET
        usable = nw - 2 * inset
        count = len(edges)
        for i, e in enumerate(edges):
            frac = 0.5 if count == 1 else i / (count - 1)
            ports[e["_idx"]] = nx + inset + usable * frac
    return ports


def _assign_ports(
    edge_list: list[dict[str, Any]],
    positions: dict[str, _Pos],
) -> list[tuple[dict[str, Any], list[float], list[float]]]:
    """Assign spread-out connection points so edges don't overlap.

    Returns list of (edge, p1, p2) tuples.
    """
    # Stamp each edge with a unique index for port keying.
    for idx, edge in enumerate(edge_list):
        edge["_idx"] = idx

    out_edges: dict[str, list[dict[str, Any]]] = {}
    in_edges: dict[str, list[dict[str, Any]]] = {}
    for edge in edge_list:
        src, dst = edge["from"], edge["to"]
        if src not in positions or dst not in positions:
            continue
        out_edges.setdefault(src, []).append(edge)
        in_edges.setdefault(dst, []).append(edge)

    out_port = _spread_ports(out_edges, positions, "to")
    in_port = _spread_ports(in_edges, positions, "from")

    result: list[tuple[dict[str, Any], list[float], list[float]]] = []
    for edge in edge_list:
        eidx = edge["_idx"]
        if eidx not in out_port:
            continue
        sx, sy, sw, sh = positions[edge["from"]]
        dx, dy, dw, dh = positions[edge["to"]]
        # Same-layer edges route horizontally (side to side).
        # Compare vertical centres, not top-y, since different-height nodes
        # in a centred row have different top-y values.
        src_cy = sy + sh / 2
        dst_cy = dy + dh / 2
        if abs(src_cy - dst_cy) < 1:
            src_cx = sx + sw / 2
            dst_cx = dx + dw / 2
            if src_cx < dst_cx:
                p1 = [sx + sw, sy + sh / 2]
                p2 = [dx, dy + dh / 2]
            else:
                p1 = [sx, sy + sh / 2]
                p2 = [dx + dw, dy + dh / 2]
        else:
            p1 = [out_port[eidx], sy + sh]
            p2 = [in_port[eidx], dy]
        result.append((edge, p1, p2))
    return result


def _arrowhead(
    p1: list[float],
    p2: list[float],
    size: float = 8,
    half_w: float = 5,
) -> dict[str, Any]:
    """Return a filled triangle arrowhead at p2 aligned to the p1→p2 direction."""

    dx = p2[0] - p1[0]
    dy = p2[1] - p1[1]
    length = math.hypot(dx, dy)
    if length < 0.001:
        return {
            "cmd": "triangle",
            "p1": p2,
            "p2": p2,
            "p3": p2,
            "filled": True,
            "color": "#555555",
        }
    # Unit vector along the line (toward p2) and perpendicular.
    ux, uy = dx / length, dy / length
    px, py = -uy, ux  # perpendicular (rotated 90°)
    # Tip at p2, base pulled back along the line.
    bx, by = p2[0] - ux * size, p2[1] - uy * size
    return {
        "cmd": "triangle",
        "p1": p2,
        "p2": [bx + px * half_w, by + py * half_w],
        "p3": [bx - px * half_w, by - py * half_w],
        "filled": True,
        "color": "#555555",
    }


def _draw_edges(
    edge_list: list[dict[str, Any]],
    positions: dict[str, _Pos],
) -> list[dict[str, Any]]:
    """Emit draw commands for arrows between nodes."""
    cmds: list[dict[str, Any]] = []
    routed = _assign_ports(edge_list, positions)
    for edge, p1, p2 in routed:
        cmds.append(
            {
                "cmd": "line",
                "p1": p1,
                "p2": p2,
                "color": "#555555",
                "thickness": 2,
            }
        )
        # Arrowhead aligned to line direction.
        cmds.append(_arrowhead(p1, p2))
        label = edge.get("label", "")
        if label:
            tw = _text_width(label)
            mx = (p1[0] + p2[0]) / 2 - tw / 2
            my = (p1[1] + p2[1]) / 2 - _CHAR_H / 2
            # Background pill behind label for readability.
            lpad = 4
            cmds.append(
                {
                    "cmd": "rect",
                    "min": [mx - lpad, my - lpad],
                    "max": [mx + tw + lpad, my + _CHAR_H + lpad],
                    "rounding": 4,
                    "filled": True,
                    "color": "#1a1a2e",
                }
            )
            cmds.append(
                {
                    "cmd": "text",
                    "pos": [mx, my],
                    "text": label,
                    "color": "#999999",
                }
            )
    return cmds


def _layout_diagram(
    layers: list[dict[str, Any]],
    edges: list[dict[str, Any]] | None,
) -> tuple[int, int, list[dict[str, Any]]]:
    """Compute positions and emit draw commands for a layered diagram.

    Returns (canvas_width, canvas_height, draw_commands).
    """
    sizes = _measure_nodes(layers)
    positions, bands, canvas_w, canvas_h = _position_layers(layers, sizes)
    cmds = _draw_nodes(layers, positions, bands)
    cmds.extend(_draw_edges(edges or [], positions))
    return canvas_w, canvas_h, cmds


@mcp.tool()
def show_diagram(
    scene_id: str,
    layers: list[dict[str, Any]],
    edges: list[dict[str, Any]] | None = None,
    title: str | None = None,
) -> str:
    """Display a layered architecture diagram with boxes, arrows, and labels.

    Automatically lays out nodes in horizontal layers with color-coded boxes,
    routed arrows between layers, and safe margins. No manual coordinate
    placement needed.

    Args:
        scene_id: Unique identifier for this scene.
        layers: Layers rendered top-to-bottom. Each layer:
            {"label": "Layer Name", "nodes": [
                {"id": "node1", "label": "Display Name", "detail": "subtitle"},
                {"id": "node2", "label": "Other Node"},
            ]}
            ``label`` is shown at the left margin. ``detail`` is an optional
            second line inside the box.
        edges: Arrows between nodes across layers.
            {"from": "node1", "to": "node2", "label": "uses"}
            Arrows route from the bottom of the source node to the top of
            the destination node. Labels appear at the midpoint.
        title: Window title.

    Example — three-tier architecture::

        show_diagram(
            scene_id="arch",
            title="System Architecture",
            layers=[
                {"label": "Frontend", "nodes": [
                    {"id": "web", "label": "Web App", "detail": "React SPA"},
                    {"id": "mobile", "label": "Mobile App", "detail": "Swift"},
                ]},
                {"label": "Backend", "nodes": [
                    {"id": "api", "label": "API Server", "detail": "FastAPI"},
                ]},
                {"label": "Storage", "nodes": [
                    {"id": "db", "label": "PostgreSQL", "detail": "primary"},
                    {"id": "cache", "label": "Redis", "detail": "sessions"},
                ]},
            ],
            edges=[
                {"from": "web", "to": "api", "label": "REST"},
                {"from": "mobile", "to": "api", "label": "REST"},
                {"from": "api", "to": "db"},
                {"from": "api", "to": "cache"},
            ],
        )
    """
    canvas_w, canvas_h, cmds = _layout_diagram(layers, edges)

    draw_element: dict[str, Any] = {
        "kind": "draw",
        "id": "diagram",
        "width": canvas_w,
        "height": canvas_h,
        "bg_color": "#1a1a2e",
        "commands": cmds,
    }

    return show(scene_id, [draw_element], title=title)


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
def register_tool(
    label: str,
    tool_id: str,
    shortcut: str | None = None,
    icon: str | None = None,
) -> str:
    """Register a menu item in the Lux Tools menu.

    The item appears in the shared Tools menu alongside items from other
    MCP servers. When the user clicks it, only this server receives the
    callback via recv().

    Items are automatically removed when the server disconnects.
    """
    item: dict[str, Any] = {"label": label, "id": tool_id}
    if shortcut is not None:
        item["shortcut"] = shortcut
    if icon is not None:
        item["icon"] = icon

    def _call() -> str:
        client = _get_client()
        client.register_menu_item(item)
        return f"registered:{tool_id}"

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
def display_mode(mode: str | None = None) -> str:
    """Get or set the display mode.

    When called with no argument, returns the current mode.
    When called with "y" or "n", sets the mode and returns confirmation.

    The display mode is an advisory signal for consumer plugins.
    Lux itself always accepts show() calls regardless of mode.
    """
    config_path = resolve_config_path()

    if mode is None:
        cfg = read_config(config_path)
        return f"display:{cfg.display}"

    if mode not in ("y", "n"):
        msg = f"Invalid mode '{mode}'. Use 'y' or 'n'."
        raise ValueError(msg)

    write_field("display", mode, config_path)
    if mode == "y":
        try:
            _get_client()
        except (RuntimeError, OSError, ValueError, KeyError):
            logger.warning(
                "Eager connect on display_mode=y failed; will retry on first tool call",
                exc_info=True,
            )
    return f"display:{mode}"


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
