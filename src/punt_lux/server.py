"""Lux MCP server — expose display tools to AI agents.

Provides FastMCP tools: ``show``, ``update``, ``clear``, ``ping``,
and ``recv``.
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
        "color pickers) in a window the user can see."
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
