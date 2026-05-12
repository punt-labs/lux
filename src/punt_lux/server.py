"""Lux MCP server — expose display tools to AI agents.

Provides FastMCP tools: ``show``, ``show_table``, ``show_dashboard``,
``update``, ``clear``, ``ping``, and ``recv``.
Uses :class:`LuxClient` under the hood with lazy connection on first call.

Run via stdio transport::

    lux serve
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import threading
import time
from collections.abc import AsyncIterator, Callable
from typing import Any

from fastmcp import FastMCP

from punt_lux.apps.beads import render_beads_board
from punt_lux.client import LuxClient
from punt_lux.config import read_config, resolve_config_path, write_field
from punt_lux.paths import default_socket_path, is_display_running
from punt_lux.protocol import (
    InteractionMessage,
    Patch,
    element_from_dict,
)

logger = logging.getLogger(__name__)


async def _retry_eager_connect() -> None:
    """Background retries for eager display connect."""
    for delay in (2.0, 5.0, 10.0):
        await asyncio.sleep(delay)
        try:
            await asyncio.to_thread(_get_client)
            logger.info("Eager connect retry succeeded")
            return
        except Exception:  # noqa: BLE001
            logger.debug("Eager connect retry failed", exc_info=True)


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

    retry_task: asyncio.Task[None] | None = None
    if cfg.display == "y":
        try:
            logger.info("display=y, eagerly connecting to display server")
            await asyncio.to_thread(_get_client)
        except Exception:  # noqa: BLE001 — best-effort startup
            logger.warning(
                "Eager connect failed; scheduling retries",
                exc_info=True,
            )
            retry_task = asyncio.create_task(_retry_eager_connect())
    try:
        yield
    finally:
        if retry_task is not None and not retry_task.done():
            retry_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await retry_task


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
    lifespan=_lifespan,
)

_client: LuxClient | None = None
_client_lock = threading.RLock()

_apps_registered_for: int | None = None


def _on_beads_browser(_msg: InteractionMessage) -> None:
    """Callback: open the Beads Browser in a frame.

    Runs in a daemon thread to avoid blocking the listener thread
    (render_beads_board calls subprocess.run with a 10s timeout).
    """
    if _client is None:
        logger.warning("_on_beads_browser: client is None, ignoring menu click")
        return
    threading.Thread(target=render_beads_board, args=(_client,), daemon=True).start()


def _setup_apps(client: LuxClient) -> None:
    """Register built-in app menu items and callbacks.

    Idempotent per client identity — safe to call on every
    ``_get_client()`` invocation.
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
      Text:         {"kind": "text", "id": "t1", "content": "Hello",
                     "color": "#FF3333", "style": "heading"}
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
        no_resize      — prevent user resizing
        no_collapse    — hide the collapse button
        auto_resize    — shrink-wrap to content each frame
        no_title_bar   — hide the title bar
        no_background  — transparent frame background
        no_scrollbar   — disable scrollbars
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
            frame_layout=frame_layout,  # type: ignore[arg-type]  # validated above
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
    frame_id: str | None = None,
    frame_title: str | None = None,
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
        frame_id: Target frame for tab isolation (e.g., "beads-lux").
        frame_title: Display title for the frame (e.g., "Beads: lux").

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
    return show(
        scene_id, [table], title=title, frame_id=frame_id, frame_title=frame_title
    )


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
    """Clear the Lux display window. Removes all content.

    No-op if the display server is not running.
    """
    if not is_display_running(default_socket_path()):
        return "cleared"

    def _call() -> str:
        client = _get_client()
        client.clear()
        return "cleared"

    return _with_reconnect(_call)


@mcp.tool()
def ping() -> str:
    """Ping the display server. Returns round-trip time, "timeout", or "not running"."""
    if not is_display_running(default_socket_path()):
        return "not running"

    def _call() -> str:
        client = _get_client()
        pong = client.ping()
        if pong is None:
            return "timeout"
        if pong.ts is not None:
            rtt = time.time() - pong.ts
            return f"pong rtt={rtt:.3f}s"
        return "pong"

    return _with_reconnect(_call)


@mcp.tool()
def inspect_scene(scene_id: str) -> str:
    """Return the element tree for a scene as JSON.

    Use this to debug rendering issues -- see exactly what elements
    the display server has for a given scene_id. Returns "not running"
    if the display server is not available.
    """
    if not is_display_running(default_socket_path()):
        return "not running"

    def _call() -> str:
        client = _get_client()
        response = client.inspect_scene(scene_id)
        if response is None:
            return "timeout"
        if response.error:
            return f"error: {response.error}"
        return json.dumps(
            {"scene_id": response.scene_id, "elements": response.elements},
            indent=2,
        )

    return _with_reconnect(_call)


@mcp.tool()
def list_scenes() -> str:
    """List all active scenes and frames in the display.

    Returns JSON with scenes (scene_id, element_count, frame_id) and
    frames (frame_id, title, scene_count). Use to understand what the
    display is currently showing. Returns "not running" if the display
    server is not available.
    """
    if not is_display_running(default_socket_path()):
        return "not running"

    def _call() -> str:
        client = _get_client()
        response = client.list_scenes()
        if response is None:
            return "timeout"
        return json.dumps(
            {"scenes": response.scenes, "frames": response.frames},
            indent=2,
        )

    return _with_reconnect(_call)


@mcp.tool()
def display_mode() -> str:
    """Read the current display mode.

    Returns "display:on" or "display:off". The display mode is an advisory signal
    for consumer plugins. Lux itself always accepts show() calls
    regardless of mode.
    """
    config_path = resolve_config_path()
    cfg = read_config(config_path)
    label = "on" if cfg.display == "y" else "off"
    return f"display:{label}"


@mcp.tool()
def set_display_mode(mode: str) -> str:
    """Set the display mode to "y" (on) or "n" (off).

    When set to "y", eagerly connects to the display server.
    The display mode is an advisory signal for consumer plugins.
    """
    if mode not in ("y", "n"):
        msg = f"Invalid mode '{mode}'. Use 'y' or 'n'."
        raise ValueError(msg)

    config_path = resolve_config_path()
    write_field("display", mode, config_path)
    if mode == "y":
        try:
            _get_client()
        except (RuntimeError, OSError, ValueError, KeyError):
            logger.warning(
                "Eager connect on set_display_mode=y failed; "
                "will retry on first tool call",
                exc_info=True,
            )
    label = "on" if mode == "y" else "off"
    return f"display:{label}"


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
