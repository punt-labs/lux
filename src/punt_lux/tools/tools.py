"""All 29 MCP tool definitions for the Lux display surface."""

from __future__ import annotations

import json
import time
from typing import Any, get_args

from punt_lux.domain.hub import client_registry, hub, hub_display
from punt_lux.domain.hub.display_connection import HubDisplayConnection
from punt_lux.domain.hub.hub_factory import hub_element_factory
from punt_lux.domain.hub.inbox import ensure_writer, next_event
from punt_lux.domain.hub.menu_registry import hub_menu_registry
from punt_lux.domain.hub.replicator_instance import hub_replicator
from punt_lux.domain.ids import ConnectionId
from punt_lux.operations import (
    ClientList,
    DisplayInfo,
    DisplayModeRequest,
    DisplayModeState,
    FrameStatePatch,
    MenuAction,
    MenuList,
    Operations,
    OpError,
    RecentErrors,
    RecentEvents,
    RenderDashboardRequest,
    RenderRequest,
    RenderTableRequest,
    SceneInspection,
    SceneList,
    SceneShown,
    Scope,
    SetMenuRequest,
    SetThemeRequest,
    ThemeName,
    ThemeState,
    UpdateRequest,
    WindowSettings,
    WindowSettingsPatch,
)
from punt_lux.operations.ports import HubPorts
from punt_lux.paths import DisplayPaths
from punt_lux.tools.server import _session_key, mcp


def _hub_ports() -> HubPorts:
    """Bundle the Hub helpers (element decode, inbox) the operations compose."""
    return HubPorts(
        element_factory=hub_element_factory,
        ensure_writer=ensure_writer,
        next_event=next_event,
    )


def _display_connection() -> HubDisplayConnection:
    """Build luxd's one bounded connection to the display for proxied ops."""
    return HubDisplayConnection(
        is_running=lambda: DisplayPaths().is_running(),
        clients=client_registry,
    )


def _build_operations() -> Operations:
    """Compose the operations facade — the presentation-layer composition root.

    Every collaborator is injected here; nothing under ``operations/`` binds a
    process singleton or reaches back into ``tools/`` at import time.
    """
    return Operations.for_store(
        hub_display,
        hub_replicator,
        hub=hub,
        client_registry=client_registry,
        menu_registry=hub_menu_registry,
        ports=_hub_ports(),
        display_port=_display_connection(),
    )


def _now() -> float:
    """Return the wall clock — a seam the ping adapter reads for its round-trip."""
    return time.time()


# The process-wide operations facade, built once at the composition root.
OPERATIONS = _build_operations()


def _connection_id() -> ConnectionId:
    """Return the calling MCP session's ``ConnectionId``."""
    return ConnectionId(_session_key.get())


def _scope() -> Scope:
    """Resolve the calling MCP session's operation scope."""
    return Scope(_connection_id())


def _format_render(result: SceneShown | OpError) -> str:
    """Render a ``render``/``render_table``/``render_dashboard`` result.

    A parse-level ``invalid_request`` carries the specific legacy message with no
    prefix; every other rejection (submission gate, undecodable element) is a
    ``"scene not rendered — "`` error.
    """
    if isinstance(result, SceneShown):
        return f"shown:{result.scene_id}"
    if result.code == "invalid_request":
        return f"error: {result.reason}"
    return f"error: scene not rendered — {result.reason}"


def _format_update(result: SceneShown | OpError) -> str:
    """Render an ``update`` result as its legacy status line."""
    if isinstance(result, SceneShown):
        return f"shown:{result.scene_id}"
    return f"error: scene not updated — {result.reason}"


def _format_display_mode(result: DisplayModeState | OpError) -> str:
    """Render a display-mode result, reproducing the legacy ValueError on error.

    The operation never raises; the MCP tools historically raised ``ValueError``
    for a bad mode or repo, so the adapter re-raises with the same message.
    """
    if isinstance(result, OpError):
        raise ValueError(result.reason)
    return f"display:{result.mode}"


def _fault_line(err: OpError) -> str:
    """Render a proxied operation's ``OpError`` as its legacy status line.

    A display that is not running reads ``"not running"`` and a bounded round-trip
    that elapsed reads ``"timeout"``, matching the two short-circuits the display
    tools returned before; every other cause reads ``"error: <reason>"``.
    """
    if err.code == "display_unavailable":
        return "not running"
    if err.code == "timeout":
        return "timeout"
    return f"error: {err.reason}"


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
    return _format_render(OPERATIONS.render(request, scope=_scope()))


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
    return _format_render(OPERATIONS.render_table(request, scope=_scope()))


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
    return _format_render(OPERATIONS.render_dashboard(request, scope=_scope()))


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
    return _format_update(
        OPERATIONS.update(scene_id, UpdateRequest.parse(patches), scope=_scope())
    )


@mcp.tool()
def set_menu(menus: list[dict[str, Any]]) -> str:
    """Add custom menus to the Lux display menu bar; clicks arrive via recv().

    Each menu: {"label": "Tools", "items": [{"label": "Run", "id": "run_btn"},
    {"label": "---"}]}  — a ``"---"`` label is a separator.

    The menu bar is Hub-owned: this writes the Hub menu registry and the
    background replicator pushes the bar to the display.
    """
    result = OPERATIONS.set_menu(SetMenuRequest.parse(menus))
    if isinstance(result, OpError):
        return _fault_line(result)
    return "ok"


@mcp.tool()
def register_tool(
    label: str,
    tool_id: str,
    shortcut: str | None = None,
    icon: str | None = None,
) -> str:
    """Register a menu item in the shared Lux Tools menu.

    Only this server receives the click via recv(). The item is scoped to this
    session in the Hub menu registry and removed when the session disconnects.
    """
    OPERATIONS.register_menu_item(
        MenuAction(id=tool_id, label=label, shortcut=shortcut, icon=icon),
        scope=_scope(),
    )
    return f"registered:{tool_id}"


# One source for the theme names — description and accepted set cannot drift.
_SET_THEME_DESCRIPTION = "Set the Lux display theme. Valid names (snake_case): " + (
    ", ".join(get_args(ThemeName))
)


@mcp.tool(description=_SET_THEME_DESCRIPTION)
def set_theme(theme: str) -> str:
    result = OPERATIONS.set_theme(SetThemeRequest.parse(theme))
    if isinstance(result, OpError):
        return _fault_line(result)
    return f"theme:{result.payload.get('theme', theme)}"


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
    result = OPERATIONS.set_window_settings(
        WindowSettingsPatch.parse(
            {
                "opacity": opacity,
                "font_scale": font_scale,
                "decorated": decorated,
                "fps_idle": fps_idle,
            }
        )
    )
    if isinstance(result, OpError):
        return _fault_line(result)
    return json.dumps(result.payload, indent=2)


@mcp.tool()
def set_frame_state(
    frame_id: str,
    minimized: bool | None = None,  # noqa: FBT001
) -> str:
    """Modify a frame's state (minimize/expand).

    Args:
        frame_id: Target frame identifier.
        minimized: True to minimize, False to expand.
    """
    result = OPERATIONS.set_frame_state(
        frame_id, FrameStatePatch.parse({"minimized": minimized})
    )
    if isinstance(result, OpError):
        return _fault_line(result)
    return json.dumps(result.payload, indent=2)


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
    result = OPERATIONS.ping(now=_now())
    if isinstance(result, OpError):
        return _fault_line(result)
    return f"pong rtt={result.rtt_seconds:.3f}s"


@mcp.tool()
def inspect_scene(scene_id: str) -> SceneInspection | OpError:
    """Return the element tree for a scene, read from the authoritative store.

    Each element reports its render path ("abc" or "legacy") and its resolved
    state including defaults, so you can verify what the Hub holds without
    inspecting pixels. An unknown scene is a not_found error.
    """
    return OPERATIONS.inspect_scene(scene_id)


@mcp.tool()
def list_scenes() -> SceneList:
    """List all active scenes and frames from the authoritative store.

    Returns the scenes (scene_id, element_count, frame_id, owner) and frames
    (frame_id, title, scene_count, scene_ids, layout) the Hub is holding.
    """
    return OPERATIONS.list_scenes()


@mcp.tool()
def screenshot() -> str:
    """Capture a screenshot of the display window.

    Returns the file path to a PNG image of the current display.
    The agent can read this image to see exactly what is rendered.
    Returns "not running" if the display server is not available.
    """
    result = OPERATIONS.screenshot()
    if isinstance(result, OpError):
        return _fault_line(result)
    return str(result.path)


@mcp.tool()
def get_display_info() -> DisplayInfo | OpError:
    """Return display server metadata: backend, resolution, FPS, PID, uptime.

    The result is a typed record; its MCP output schema is derived from that
    record, so the display's own reply can never be rejected by a schema that
    drifted from it.
    """
    return OPERATIONS.get_display_info()


@mcp.tool()
def get_window_settings() -> WindowSettings | OpError:
    """Return current window settings: opacity, font scale, decoration, idle FPS."""
    return OPERATIONS.get_window_settings()


@mcp.tool()
def get_theme() -> ThemeState | OpError:
    """Return current theme and available themes."""
    return OPERATIONS.get_theme()


@mcp.tool()
def list_clients() -> ClientList:
    """List the Hub's sessions — the connections and their scopes.

    After the Hub took over, the display has one socket client (luxd); the
    meaningful client list is the set of Hub sessions the Hub holds.
    """
    return OPERATIONS.list_clients(now=_now())


@mcp.tool()
def list_menus() -> MenuList:
    """List the Hub-owned menu bar and its items, read with no reach-around."""
    return OPERATIONS.list_menus()


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
        OPERATIONS.write_display_mode(DisplayModeRequest.parse(mode, repo))
    )


@mcp.tool()
def list_recent_events(count: int = 50) -> RecentEvents | OpError:
    """Return the last N interaction events from the display.

    Events include button clicks, slider changes, combo selections, and other
    user interactions. Default 50, max 200. Proxied over luxd's one connection.
    """
    return OPERATIONS.list_recent_events(count)


@mcp.tool()
def list_errors(count: int = 20) -> RecentErrors | OpError:
    """Return the last N display-side errors and warnings.

    Each entry includes timestamp, severity, message, and context. Default 20,
    max 100. Proxied over luxd's one connection.
    """
    return OPERATIONS.list_errors(count)
