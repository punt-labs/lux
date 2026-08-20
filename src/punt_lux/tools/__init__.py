"""Lux MCP server — expose display tools to AI agents.

Every tool is a thin adapter over the ``Operations`` facade (render, settings,
introspection, ``identify``, pub/sub); luxd serves them over streamable-HTTP ``/mcp``.
"""

# isort: skip_file
# ORDER MATTERS: server.py creates the FastMCP `mcp` instance; tools.py builds
# OPERATIONS; the tool modules register @mcp.tool() at import time.

from __future__ import annotations

from punt_lux.tools.server import mcp

from punt_lux.tools.read_tools import (
    get_display_info,
    get_theme,
    get_window_settings,
    inspect_scene,
    list_clients,
    list_errors,
    list_menus,
    list_recent_events,
    list_scenes,
    ping,
    screenshot,
)

from punt_lux.tools.write_tools import clear, clear_scene, identify, show, update
from punt_lux.tools.display_write_tools import (
    display_mode,
    frame_close,
    frame_raise,
    set_display_mode,
    set_menu,
    set_theme,
    set_window_settings,
)
from punt_lux.tools.composite_tools import show_dashboard, show_table
from punt_lux.tools.subscribe_tools import (
    pending_callbacks,
    publish,
    recv,
    register_callback,
    subscribe,
    unsubscribe,
)

__all__ = [
    "clear",
    "clear_scene",
    "display_mode",
    "frame_close",
    "frame_raise",
    "get_display_info",
    "get_theme",
    "get_window_settings",
    "identify",
    "inspect_scene",
    "list_clients",
    "list_errors",
    "list_menus",
    "list_recent_events",
    "list_scenes",
    "mcp",
    "pending_callbacks",
    "ping",
    "publish",
    "recv",
    "register_callback",
    "screenshot",
    "set_display_mode",
    "set_menu",
    "set_theme",
    "set_window_settings",
    "show",
    "show_dashboard",
    "show_table",
    "subscribe",
    "unsubscribe",
    "update",
]
