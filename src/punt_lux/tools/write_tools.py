"""The state-changing MCP tools — rendering, settings, menus, and config.

These install or mutate state: ``show``/``update`` write scenes, ``set_*`` change
theme/window/frame/menu state, ``clear`` empties the display, and the
``display_mode`` pair reads and writes the per-repo config. They are split from
the read-only tools in ``read_tools`` so neither module carries the whole surface.

``_core.OPERATIONS`` and the shared formatters are read at call time, never
imported by value: the characterization corpus rebinds
``punt_lux.tools.tools.OPERATIONS`` to route at an isolated store, and a
value-import would freeze the production facade past that rebind (the shape
``composite_tools`` established).
"""

from __future__ import annotations

from typing import Any, get_args

from punt_lux.operations import (
    DisplayModeRequest,
    FrameStatePatch,
    Ok,
    OpError,
    RegisterToolRequest,
    RenderRequest,
    SetMenuRequest,
    SetThemeRequest,
    ThemeName,
    ThemeState,
    UpdateRequest,
    WindowSettings,
    WindowSettingsPatch,
)
from punt_lux.operations.models.window import (
    FONT_SCALE_RANGE,
    FPS_IDLE_RANGE,
    OPACITY_RANGE,
)
from punt_lux.tools import tools as _core
from punt_lux.tools.server import mcp

__all__ = [
    "clear",
    "display_mode",
    "register_tool",
    "set_display_mode",
    "set_frame_state",
    "set_menu",
    "set_theme",
    "set_window_settings",
    "show",
    "update",
]


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
    frame_ttl_seconds: float | None = None,
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

    Frame sizing:
      frame_size:  [width, height] in pixels — initial size hint (first use only).
      frame_flags: ImGui window flag keys, each true/false — no_resize, no_collapse,
        auto_resize, no_title_bar, no_background, no_scrollbar.
      frame_layout: how multiple scenes share the frame — "tab" (one at a time via a
        tab bar, default) or "stack" (stacked with collapsing headers).
      frame_ttl_seconds: a positive lifetime after which the Hub removes the frame
        and its scenes from both tiers, unless a re-show refreshes it first. Omit
        (the default) for a frame that never expires; a re-show with no TTL clears
        a prior one.

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
                "ttl_seconds": frame_ttl_seconds,
            },
        }
    )
    return _core._format_render(_core.OPERATIONS.render(request, scope=_core._scope()))


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
    return _core._format_update(
        _core.OPERATIONS.update(
            scene_id, UpdateRequest.parse(patches), scope=_core._scope()
        )
    )


@mcp.tool()
def set_menu(menus: list[dict[str, Any]]) -> str:
    """Add custom menus to the Lux display menu bar; clicks arrive via recv().

    Each menu: {"label": "Tools", "items": [{"label": "Run", "id": "run_btn"},
    {"label": "---"}]}  — a ``"---"`` label is a separator.

    The menu bar is Hub-owned: this writes the Hub menu registry and the
    background replicator pushes the bar to the display.
    """
    return _core._fault_or(
        _core.OPERATIONS.set_menu(SetMenuRequest.parse(menus)), lambda _r: "ok"
    )


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
    return _core._fault_or(
        _core.OPERATIONS.register_menu_item(
            RegisterToolRequest.parse(
                tool_id=tool_id, label=label, shortcut=shortcut, icon=icon
            ),
            scope=_core._scope(),
        ),
        lambda _r: f"registered:{tool_id}",
    )


# One source for the theme names — description and accepted set cannot drift.
_SET_THEME_DESCRIPTION = "Set the Lux display theme. Valid names (snake_case): " + (
    ", ".join(get_args(ThemeName))
)


# Bounds come from the WindowSettingsPatch ranges — one source, no drift.
_SET_WINDOW_DESCRIPTION = (
    "Modify display window settings. Only provided fields change. "
    f"Fields: opacity ({OPACITY_RANGE[0]}-{OPACITY_RANGE[1]}), "
    f"font_scale ({FONT_SCALE_RANGE[0]}-{FONT_SCALE_RANGE[1]}), "
    "decorated (title bar/borders), "
    f"fps_idle (target idle FPS, {FPS_IDLE_RANGE[0]}-{FPS_IDLE_RANGE[1]})."
)


@mcp.tool(description=_SET_THEME_DESCRIPTION)
def set_theme(theme: str) -> ThemeState | OpError:
    """Set the display theme; returns the new theme state or an error."""
    return _core.OPERATIONS.set_theme(SetThemeRequest.parse(theme))


@mcp.tool(description=_SET_WINDOW_DESCRIPTION)
def set_window_settings(
    opacity: float | None = None,
    font_scale: float | None = None,
    decorated: bool | None = None,  # noqa: FBT001
    fps_idle: float | None = None,
) -> WindowSettings | OpError:
    """Change the provided window settings; returns the new settings or an error."""
    return _core.OPERATIONS.set_window_settings(
        WindowSettingsPatch.parse(
            {
                "opacity": opacity,
                "font_scale": font_scale,
                "decorated": decorated,
                "fps_idle": fps_idle,
            }
        )
    )


@mcp.tool()
def set_frame_state(
    frame_id: str,
    minimized: bool | None = None,  # noqa: FBT001
) -> Ok | OpError:
    """Minimize or expand a frame (``minimized`` true to minimize)."""
    return _core.OPERATIONS.set_frame_state(
        frame_id, FrameStatePatch.parse({"minimized": minimized})
    )


@mcp.tool()
def clear() -> str:
    """Clear the Lux display window. Returns ``"cleared"``.

    The Hub store is the authority, so emptying it never hinges on the display
    being up: every scene the caller owns is removed, the replicator is told the
    screen was cleared, and the tool returns at once — the replicator blanks the
    display in the background. The blank is global (ALL rendered scenes, not only
    the caller's) for the single-connection slice; per-caller scoping is a
    separate change.
    """
    _core.OPERATIONS.clear(scope=_core._scope())
    return "cleared"


@mcp.tool()
def display_mode(repo: str) -> str:
    """Read the current display mode.

    Returns "display:on" or "display:off". ``repo`` must be the
    absolute path of the caller's project; the config is read from
    ``<repo>/.punt-labs/lux.md``.
    """
    return _core._format_display_mode(_core.OPERATIONS.read_display_mode(repo))


@mcp.tool()
def set_display_mode(mode: str, repo: str) -> str:
    """Set the display mode to "y" (on) or "n" (off).

    ``repo`` must be the absolute path of the caller's project; the
    config is written to ``<repo>/.punt-labs/lux.md``.
    When ``y``, eagerly connects to the display server.
    """
    return _core._format_display_mode(
        _core.OPERATIONS.write_display_mode(DisplayModeRequest.parse(mode, repo))
    )
