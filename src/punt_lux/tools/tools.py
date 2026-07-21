"""All 29 MCP tool definitions for the Lux display surface."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from punt_lux.domain.hub import client_registry
from punt_lux.domain.ids import ConnectionId
from punt_lux.operations import (
    DisplayModeRequest,
    DisplayModeState,
    Operations,
    OpError,
    RenderDashboardRequest,
    RenderRequest,
    RenderTableRequest,
    SceneShown,
    Scope,
    UpdateRequest,
)
from punt_lux.operations.ports import HubPorts
from punt_lux.paths import DisplayPaths
from punt_lux.tools.connection import _query_tool
from punt_lux.tools.hub_factory import hub_element_factory
from punt_lux.tools.inbox import ensure_writer, next_event
from punt_lux.tools.server import (
    _session_key,
    _session_menus,
    mcp,
)

if TYPE_CHECKING:
    from punt_lux.display_client import DisplayClient

# The process-wide operations facade. This is where the composition crosses the
# layer boundary: the operations layer stays pure engine core, and the two Hub
# helpers it needs — connection-scoped element decode and the session inbox —
# are injected here in the presentation layer, so nothing under ``operations/``
# imports back up into ``tools/``.
OPERATIONS = Operations.production(
    HubPorts(
        element_factory=hub_element_factory,
        ensure_writer=ensure_writer,
        next_event=next_event,
    )
)


def _connection_id() -> ConnectionId:
    """Return the calling MCP session's ``ConnectionId``."""
    return ConnectionId(_session_key.get())


def _scope() -> Scope:
    """Resolve the calling MCP session's operation scope."""
    return Scope(_connection_id())


def _format_scene(result: SceneShown | OpError) -> str:
    """Render a scene-mutation result as the tool's legacy status line."""
    if isinstance(result, OpError):
        return f"error: {result.reason}"
    return f"shown:{result.scene_id}"


def _format_display_mode(result: DisplayModeState) -> str:
    """Render a display-mode result as ``display:on`` / ``display:off``."""
    return f"display:{result.mode}"


def _display_running() -> bool:
    """Whether a live display process owns the socket."""
    return DisplayPaths().is_running()


def _client() -> DisplayClient:
    """Return the Hub's connected display client for a read-only round-trip."""
    return client_registry.get()


def _bounded(call: Callable[[], str]) -> str:
    """Run a ``set_*`` round-trip; return ``"timeout"`` if the send fails.

    The ``SO_SNDTIMEO``-bounded send raises ``OSError`` within the limit; the tool
    drops the dead connection so the next ``set_*`` reconnects, and reports
    ``"timeout"`` — never killing the display.
    """
    try:
        return call()
    except OSError:
        client_registry.drop()
        return "timeout"


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
      Markdown:     {"kind": "markdown", "id": "md1", "content": "# Title\\n**bold**"}

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

    All elements with an id support an optional ``"tooltip"`` (shown on hover).

    Frame sizing (only with ``frame_id``):
      frame_size:  [width, height] in pixels — initial size hint (first use only).
      frame_flags: ImGui window flag keys, each true/false — no_resize, no_collapse,
        auto_resize, no_title_bar, no_background, no_scrollbar.
      frame_layout: how multiple scenes share the frame — "tab" (one at a time via a
        tab bar, default) or "stack" (stacked with collapsing headers).

    Writes the scene to the Hub and returns ``"shown:<scene_id>"`` at once — the
    replicator sends it in the background; "shown" means accepted, not drawn.
    """
    request = RenderRequest.parse(
        {
            "scene_id": scene_id,
            "elements": elements,
            "title": title,
            "layout": layout,
            "frame": {
                "frame_id": frame_id,
                "frame_title": frame_title,
                "size": frame_size,
                "flags": frame_flags,
                "layout": frame_layout,
            },
        }
    )
    return _format_scene(OPERATIONS.render(request, scope=_scope()))


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
    request = RenderTableRequest.parse(
        {
            "scene_id": scene_id,
            "columns": columns,
            "rows": rows,
            "filters": filters,
            "detail": detail,
            "flags": flags,
            "title": title,
            "frame_id": frame_id,
            "frame_title": frame_title,
        }
    )
    return _format_scene(OPERATIONS.render_table(request, scope=_scope()))


@mcp.tool()
def show_dashboard(
    scene_id: str,
    metrics: list[dict[str, str]] | None = None,
    charts: list[dict[str, Any]] | None = None,
    table_columns: list[str] | None = None,
    table_rows: list[list[Any]] | None = None,
    title: str | None = None,
    frame_id: str | None = None,
    frame_title: str | None = None,
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
    request = RenderDashboardRequest.parse(
        {
            "scene_id": scene_id,
            "metrics": metrics,
            "charts": charts,
            "table_columns": table_columns,
            "table_rows": table_rows,
            "title": title,
            "frame_id": frame_id,
            "frame_title": frame_title,
        }
    )
    return _format_scene(OPERATIONS.render_dashboard(request, scope=_scope()))


@mcp.tool()
def update(scene_id: str, patches: list[dict[str, Any]]) -> str:
    """Update elements in the current scene without replacing everything.

    Each patch targets an element by id and can set fields or remove it:
      {"id": "t1", "set": {"content": "Updated text"}}  or  {"id": "b1", "remove": true}

    The Hub mutates its authoritative store and marks the scene dirty; the
    background replicator re-sends it, the same replication a click takes, and the
    tool returns ``"shown:<scene_id>"``. A rejected write — an invalid patch, an
    unknown field, or a ``set`` that would break an element — mutates nothing and
    returns ``"error: scene not updated — <reason>"``.
    """
    return _format_scene(
        OPERATIONS.update(scene_id, UpdateRequest.parse(patches), scope=_scope())
    )


@mcp.tool()
def set_menu(menus: list[dict[str, Any]]) -> str:
    """Add custom menus to the Lux display menu bar; clicks arrive via recv().

    Each menu: {"label": "Tools", "items": [{"label": "Run", "id": "run_btn"},
    {"label": "---"}]}  — a ``"---"`` label is a separator.
    """

    def _call() -> str:
        client = _client()
        client.set_menu(menus)
        return "ok"

    return _bounded(_call)


@mcp.tool()
def register_tool(
    label: str,
    tool_id: str,
    shortcut: str | None = None,
    icon: str | None = None,
) -> str:
    """Register a menu item in the shared Lux Tools menu.

    Only this server receives the click via recv(). The item is removed
    automatically when the server disconnects.
    """
    item: dict[str, Any] = {"label": label, "id": tool_id}
    if shortcut is not None:
        item["shortcut"] = shortcut
    if icon is not None:
        item["icon"] = icon

    def _call() -> str:
        client = _client()
        client.register_menu_item(item)
        with client_registry.lock:
            key = _session_key.get()
            _session_menus.setdefault(key, []).append(tool_id)
        return f"registered:{tool_id}"

    return _bounded(_call)


@mcp.tool()
def set_theme(theme: str) -> str:
    """Set the Lux display theme.

    Available themes (snake_case names):
      imgui_colors_light, imgui_colors_dark, imgui_colors_classic,
      darcula, darcula_darker, material_flat, photoshop_style,
      grey_flat, cherry, light_rounded, microsoft_style, from_imgui_colors_dark
    """
    if not _display_running():
        return "not running"

    def _call() -> str:
        client = _client()
        response = client.query("set_theme", {"theme": theme})
        if response is None:
            return "timeout"
        if response.error:
            return f"error: {response.error}"
        return f"theme:{response.result.get('theme', theme)}"

    return _bounded(_call)


@mcp.tool()
def set_window_settings(
    opacity: float | None = None,
    font_scale: float | None = None,
    decorated: bool | None = None,  # noqa: FBT001
    fps_idle: float | None = None,
) -> str:
    """Modify display window settings. Only provided fields change.

    Fields: opacity (0.1-1.0), font_scale (0.5-3.0), decorated (title bar/borders),
    fps_idle (target idle FPS, 1-120).
    """
    params: dict[str, Any] = {}
    if opacity is not None:
        params["opacity"] = opacity
    if font_scale is not None:
        params["font_scale"] = font_scale
    if decorated is not None:
        params["decorated"] = decorated
    if fps_idle is not None:
        params["fps_idle"] = fps_idle
    if not params:
        return "error: no settings provided"
    if not _display_running():
        return "not running"

    def _call() -> str:
        client = _client()
        response = client.query("set_window_settings", params)
        if response is None:
            return "timeout"
        if response.error:
            return f"error: {response.error}"
        return json.dumps(response.result, indent=2)

    return _bounded(_call)


@_query_tool(
    "set_frame_state",
    doc="Modify a frame's state (minimize/expand).\n\n"
    "Args:\n"
    "    frame_id: Target frame identifier.\n"
    "    minimized: True to minimize, False to expand.",
)
def set_frame_state(
    frame_id: str,
    minimized: bool | None = None,  # noqa: FBT001
) -> dict[str, Any] | None:
    """Modify a frame's state (minimize/expand)."""
    params: dict[str, Any] = {"frame_id": frame_id}
    if minimized is not None:
        params["minimized"] = minimized
    return params


@mcp.tool()
def clear() -> str:
    """Clear the Lux display window. Returns ``"cleared"``.

    The Hub store is the authority, so emptying it never hinges on the display
    being up: every scene the caller owns is removed, the replicator is told the
    screen was cleared, and the tool returns at once — the replicator blanks the
    display in the background. The blank is global (ALL rendered scenes, not only
    the caller's), honest for the single-connection slice; per-caller scoping is
    a separate change.
    """
    OPERATIONS.clear(scope=_scope())
    return "cleared"


@mcp.tool()
def ping() -> str:
    """Ping the display server. Returns round-trip time, "timeout", or "not running"."""
    if not _display_running():
        return "not running"

    def _call() -> str:
        client = _client()
        pong = client.ping()
        if pong is None:
            return "timeout"
        if pong.ts is not None:
            rtt = time.time() - pong.ts
            return f"pong rtt={rtt:.3f}s"
        return "pong"

    return client_registry.with_reconnect(_call)


@mcp.tool()
def inspect_scene(scene_id: str) -> str:
    """Return the element tree for a scene as JSON.

    Use this to debug rendering issues -- see exactly what elements
    the display server has for a given scene_id. Returns "not running"
    if the display server is not available.
    """
    if not _display_running():
        return "not running"

    def _call() -> str:
        client = _client()
        response = client.query("inspect_scene", {"scene_id": scene_id})
        if response is None:
            return "timeout"
        if response.error:
            return f"error: {response.error}"
        return json.dumps(response.result, indent=2)

    return client_registry.with_reconnect(_call)


@mcp.tool()
def list_scenes() -> str:
    """List all active scenes and frames in the display.

    Returns JSON with scenes (scene_id, element_count, frame_id) and
    frames (frame_id, title, scene_count). Use to understand what the
    display is currently showing. Returns "not running" if the display
    server is not available.
    """
    if not _display_running():
        return "not running"

    def _call() -> str:
        client = _client()
        response = client.query("list_scenes")
        if response is None:
            return "timeout"
        return json.dumps(response.result, indent=2)

    return client_registry.with_reconnect(_call)


@mcp.tool()
def screenshot() -> str:
    """Capture a screenshot of the display window.

    Returns the file path to a PNG image of the current display.
    The agent can read this image to see exactly what is rendered.
    Returns "not running" if the display server is not available.
    """
    if not _display_running():
        return "not running"

    def _call() -> str:
        client = _client()
        response = client.query("screenshot")
        if response is None:
            return "timeout"
        if response.error:
            return f"error: {response.error}"
        return str(response.result.get("path", ""))

    return client_registry.with_reconnect(_call)


@_query_tool(
    "get_display_info",
    doc="Return display server metadata: backend, resolution, FPS, PID, uptime.",
)
def get_display_info() -> dict[str, Any] | None:
    """Return display server metadata."""
    return None


@_query_tool(
    "get_window_settings",
    doc="Return current window settings: font scale, idle FPS.",
)
def get_window_settings() -> dict[str, Any] | None:
    """Return current window settings."""
    return None


@_query_tool("get_theme", doc="Return current theme and available themes.")
def get_theme() -> dict[str, Any] | None:
    """Return current theme and available themes."""
    return None


@_query_tool(
    "list_clients",
    doc="List all clients connected to the display server.",
)
def list_clients() -> dict[str, Any] | None:
    """List all clients connected to the display server."""
    return None


@_query_tool(
    "list_menus",
    doc="List all registered menus and their items.",
)
def list_menus() -> dict[str, Any] | None:
    """List all registered menus and their items."""
    return None


@mcp.tool()
def display_mode(repo: str) -> str:
    """Read the current display mode.

    Returns "display:on" or "display:off". ``repo`` must be the
    absolute path of the caller's project; the config is read from
    ``<repo>/.punt-labs/lux.md``.
    """
    return _format_display_mode(OPERATIONS.read_display_mode(repo))


@mcp.tool()
def set_display_mode(mode: str, repo: str) -> str:
    """Set the display mode to "y" (on) or "n" (off).

    ``repo`` must be the absolute path of the caller's project; the
    config is written to ``<repo>/.punt-labs/lux.md``.
    When ``y``, eagerly connects to the display server.
    """
    return _format_display_mode(
        OPERATIONS.write_display_mode(DisplayModeRequest.from_toggle(mode, repo))
    )


@_query_tool(
    "list_recent_events",
    doc="Return the last N interaction events from the display.\n\n"
    "Events include button clicks, slider changes, combo selections,\n"
    "and other user interactions. Default 50, max 200.",
)
def list_recent_events(count: int = 50) -> dict[str, Any] | None:
    """Return the last N interaction events."""
    return {"count": count}


@_query_tool(
    "list_errors",
    doc="Return the last N display-side errors and warnings.\n\n"
    "Each entry includes timestamp, severity, message, and context.\n"
    "Default 20, max 100.",
)
def list_errors(count: int = 20) -> dict[str, Any] | None:
    """Return the last N display-side errors."""
    return {"count": count}
