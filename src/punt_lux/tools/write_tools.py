"""The state-changing MCP tools for scene writes.

``show``/``update`` write scenes, ``clear``/``clear_scene`` empty them, and
``identify`` declares the caller. Display/menu/config state changes
(``set_menu``, ``set_theme``, ``set_window_settings``, ``set_frame_state``,
``display_mode``, ``set_display_mode``) live in ``display_write_tools`` so
neither module mixes the scene concern with the display/config one.

``_core.OPERATIONS`` and the shared formatters are read at call time, never
imported by value: the characterization corpus rebinds
``punt_lux.tools.tools.OPERATIONS`` to route at an isolated store, and a
value-import would freeze the production facade past that rebind (the shape
``composite_tools`` established).
"""

from __future__ import annotations

import asyncio
from typing import Any, Literal

from punt_lux.commands import (
    Ctx as CommandCtx,
    SceneOps,
    scene_clear as scene_clear_command,
    scene_clear_all as scene_clear_all_command,
    scene_show as scene_show_command,
    scene_update as scene_update_command,
)
from punt_lux.domain.hub.scene_presentation import SceneLayout
from punt_lux.operations import RenderRequest, UpdateRequest
from punt_lux.tools import tools as _core
from punt_lux.tools.server import mcp

__all__ = [
    "clear",
    "clear_scene",
    "identify",
    "show",
    "update",
]


@mcp.tool()
def identify(
    kind: str,
    name: str,
    repo: str | None = None,
    agent: str | None = None,
) -> str:
    """Declare who this session is so the Hub attributes the UI it installs.

    ``kind`` is one of "mcp-session", "cli", or "app"; ``name`` is the label
    introspection shows for you; ``repo`` is the absolute path of your project
    (omit when headless); ``agent`` is your persona handle when you are an agent.
    Returns "identified:<name>", or "error: <reason>" for a malformed declaration.
    """
    return _core._fault_or(
        _core.OPERATIONS.identify(
            {"kind": kind, "name": name, "repo": repo, "agent": agent},
            scope=_core._scope(),
        ),
        lambda result: f"identified:{result.identity.name}",
    )


@mcp.tool()
def show(
    scene_id: str,
    elements: list[dict[str, Any]],
    title: str | None = None,
    layout: SceneLayout = "single",
    frame_id: str | None = None,
    frame_title: str | None = None,
    frame_size: list[int] | None = None,
    frame_flags: dict[str, bool] | None = None,
    frame_layout: Literal["tab", "stack"] | None = None,
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
      Tab bar:      {"kind": "tab_bar", "id": "tb1",
                     "tabs": [{"label": "Tab 1", "children": [...]}, ...]}
      Collapsing:   {"kind": "collapsing_header", "id": "ch1", "label": "Details",
                     "default_open": true, "children": [...]}
      Window:       {"kind": "window", "id": "w1", "title": "Panel", "x": 50,
                     "y": 50, "width": 300, "height": 200, "children": [...]}

    All elements with an id support an optional ``"tooltip"`` (shown on hover).

    Frame sizing:
      frame_size:  [width, height] in pixels — initial size hint (first use only).
      frame_flags: ImGui window flag keys, each true/false — no_resize, no_collapse,
        auto_resize, no_title_bar, no_background, no_scrollbar.
      frame_layout: how multiple scenes share the frame — "tab" (one at a time via a
        tab bar, default) or "stack" (stacked with collapsing headers).
      frame_ttl_seconds: positive lifetime after which the Hub removes the frame and
        its scenes, unless a re-show refreshes it; omit for a frame that never expires.

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
    ctx: CommandCtx[SceneOps] = CommandCtx(
        ops=_core.OPERATIONS, identity=_core._identity()
    )
    result = asyncio.run(scene_show_command(ctx, request, scope=_core._scope()))
    return result.text


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
    ctx: CommandCtx[SceneOps] = CommandCtx(
        ops=_core.OPERATIONS, identity=_core._identity()
    )
    result = asyncio.run(
        scene_update_command(
            ctx, scene_id, UpdateRequest.parse(patches), scope=_core._scope()
        )
    )
    return result.text


@mcp.tool()
def clear() -> str:
    """Clear every scene you own (not other agents' UI); use ``clear_scene`` for one."""
    ctx: CommandCtx[SceneOps] = CommandCtx(
        ops=_core.OPERATIONS, identity=_core._identity()
    )
    result = asyncio.run(scene_clear_all_command(ctx, scope=_core._scope()))
    return result.text


@mcp.tool()
def clear_scene(scene_id: str) -> str:
    """Clear one scene and blank its frame; only ``scene_id`` goes.

    An unknown scene, or one you own nothing in, is an error, never a false
    ``"cleared"`` — a mistyped id cannot look like a successful clear.
    """
    ctx: CommandCtx[SceneOps] = CommandCtx(
        ops=_core.OPERATIONS, identity=_core._identity()
    )
    result = asyncio.run(scene_clear_command(ctx, scene_id, scope=_core._scope()))
    return result.text
