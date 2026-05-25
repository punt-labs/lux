"""All 29 MCP tool definitions for the Lux display surface."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, cast

from punt_lux.config import ConfigManager
from punt_lux.display_client import agent_element_factory
from punt_lux.domain.element import Element as DomainElement
from punt_lux.domain.hub import client_registry, hub_display
from punt_lux.domain.ids import ConnectionId, SceneId
from punt_lux.domain.update import AddElement
from punt_lux.paths import DisplayPaths
from punt_lux.protocol import Element as WireElement, Patch
from punt_lux.tools.connection import _query_tool
from punt_lux.tools.server import (
    _session_key,
    _session_menus,
    mcp,
)

logger = logging.getLogger(__name__)


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
    if frame_id is None:
        frame_id = scene_id
    if frame_title is None:
        frame_title = title or scene_id

    factory = agent_element_factory()
    typed_elements: list[WireElement] = [factory.element_from_dict(e) for e in elements]
    size_tuple: tuple[int, int] | None = None
    if frame_size is not None:
        if len(frame_size) != 2:
            return "error: frame_size must be [width, height]"
        size_tuple = (frame_size[0], frame_size[1])
    if frame_layout is not None and frame_layout not in ("tab", "stack"):
        return f"error: frame_layout must be 'tab' or 'stack', got {frame_layout!r}"

    def _call() -> str:
        client = client_registry.get()
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
        _index_scene_in_hub(scene_id, typed_elements)
        return f"ack:{ack.scene_id}"

    return client_registry.with_reconnect(_call)


def _index_scene_in_hub(scene_id: str, typed_elements: list[WireElement]) -> None:
    """Mirror the displayed scene into the HubDisplay element index.

    Without this, click resolution and connection-scoped cleanup are
    blind to anything ``show`` put on screen — ``Display.interact``
    rejects every interaction whose target was installed via ``show``,
    and ``drop_connection`` leaks the scene's roots. The Composite
    Protocol recursion inside ``HubDisplay.apply`` walks each root's
    descendants automatically.

    Every wire element class structurally satisfies the
    :class:`DomainElement` Protocol — same ``id`` / ``kind`` /
    ``to_dict`` / ``from_dict`` shape — but mypy does not infer the
    Protocol match from the wire union, so we cast at the call site
    (the display-side ``DomainPump`` carries the same cast).
    """
    connection_id = ConnectionId(_session_key.get())
    hub_display.register_client(connection_id)
    scene = SceneId(scene_id)
    for element in typed_elements:
        hub_display.apply(
            connection_id,
            AddElement(
                scene_id=scene,
                element=cast("DomainElement", element),
                parent_id=None,
            ),
        )


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

    return show(
        scene_id,
        elements,
        title=title,
        frame_id=frame_id,
        frame_title=frame_title,
    )


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
        )
        for p in patches
    ]

    def _call() -> str:
        client = client_registry.get()
        ack = client.update(scene_id, typed_patches)
        if ack is None:
            return "timeout"
        return f"ack:{ack.scene_id}"

    return client_registry.with_reconnect(_call)


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
        client = client_registry.get()
        client.set_menu(menus)
        return "ok"

    return client_registry.with_reconnect(_call)


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
        client = client_registry.get()
        client.register_menu_item(item)
        with client_registry.lock:
            key = _session_key.get()
            _session_menus.setdefault(key, []).append(tool_id)
        return f"registered:{tool_id}"

    return client_registry.with_reconnect(_call)


@mcp.tool()
def set_theme(theme: str) -> str:
    """Set the Lux display theme.

    Available themes (snake_case names):
      imgui_colors_light, imgui_colors_dark, imgui_colors_classic,
      darcula, darcula_darker, material_flat, photoshop_style,
      grey_flat, cherry, light_rounded, microsoft_style, from_imgui_colors_dark

    Example: set_theme("imgui_colors_light") for dashboards and data views.
    """
    if not DisplayPaths().is_running():
        return "not running"

    def _call() -> str:
        client = client_registry.get()
        response = client.query("set_theme", {"theme": theme})
        if response is None:
            return "timeout"
        if response.error:
            return f"error: {response.error}"
        return f"theme:{response.result.get('theme', theme)}"

    return client_registry.with_reconnect(_call)


@mcp.tool()
def set_window_settings(
    opacity: float | None = None,
    font_scale: float | None = None,
    decorated: bool | None = None,  # noqa: FBT001
    fps_idle: float | None = None,
) -> str:
    """Modify display window settings. Only provided fields are changed.

    Args:
        opacity: Window opacity (0.1-1.0).
        font_scale: Font size multiplier (0.5-3.0).
        decorated: Show window title bar and borders.
        fps_idle: Target FPS when idle (1-120).
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
    if not DisplayPaths().is_running():
        return "not running"

    def _call() -> str:
        client = client_registry.get()
        response = client.query("set_window_settings", params)
        if response is None:
            return "timeout"
        if response.error:
            return f"error: {response.error}"
        return json.dumps(response.result, indent=2)

    return client_registry.with_reconnect(_call)


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
    """Clear the Lux display window. Returns "not running" when display is off."""
    if not DisplayPaths().is_running():
        return "not running"

    def _call() -> str:
        client = client_registry.get()
        client.clear()
        return "cleared"

    return client_registry.with_reconnect(_call)


@mcp.tool()
def ping() -> str:
    """Ping the display server. Returns round-trip time, "timeout", or "not running"."""
    if not DisplayPaths().is_running():
        return "not running"

    def _call() -> str:
        client = client_registry.get()
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
    if not DisplayPaths().is_running():
        return "not running"

    def _call() -> str:
        client = client_registry.get()
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
    if not DisplayPaths().is_running():
        return "not running"

    def _call() -> str:
        client = client_registry.get()
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
    if not DisplayPaths().is_running():
        return "not running"

    def _call() -> str:
        client = client_registry.get()
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


def _config_manager_for(repo: str) -> ConfigManager:
    """Build a ConfigManager for the caller's project (lux-r929).

    ``repo`` is required and must be an absolute path to an existing
    directory. The MCP server runs inside luxd, whose cwd is wherever
    launchd started it (typically ``$HOME``) — never the agent's
    project. Every MCP caller of ``display_mode`` / ``set_display_mode``
    must therefore say what project they mean.
    """
    if not repo:
        raise ValueError("repo is required and must be a non-empty string")
    path = Path(repo)
    if not path.is_absolute():
        raise ValueError(f"repo must be an absolute path; got {repo!r}")
    if not path.exists():
        raise ValueError(f"repo path does not exist: {repo}")
    if not path.is_dir():
        raise ValueError(f"repo must be a directory; got {repo}")
    return ConfigManager(config_path=path / ".punt-labs" / "lux.md")


@mcp.tool()
def display_mode(repo: str) -> str:
    """Read the current display mode.

    Returns "display:on" or "display:off". ``repo`` must be the
    absolute path of the caller's project; the config is read from
    ``<repo>/.punt-labs/lux.md`` (lux-r929).
    """
    cfg = _config_manager_for(repo).read()
    label = "on" if cfg.display == "y" else "off"
    return f"display:{label}"


@mcp.tool()
def set_display_mode(mode: str, repo: str) -> str:
    """Set the display mode to "y" (on) or "n" (off).

    ``repo`` must be the absolute path of the caller's project; the
    config is written to ``<repo>/.punt-labs/lux.md`` (lux-r929).
    When ``y``, eagerly connects to the display server.
    """
    if mode not in ("y", "n"):
        msg = f"Invalid mode '{mode}'. Use 'y' or 'n'."
        raise ValueError(msg)

    _config_manager_for(repo).write_field("display", mode)
    if mode == "y":
        try:
            client_registry.get()
        except (RuntimeError, OSError, ValueError, KeyError):
            logger.warning(
                "Eager connect on set_display_mode=y failed; "
                "will retry on first tool call",
                exc_info=True,
            )
    label = "on" if mode == "y" else "off"
    return f"display:{label}"


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
