"""Lux MCP server — expose display tools to AI agents.

Display tools (``show``, ``update``, ``ping``, ...) use
:class:`DisplayClient`; Agent Subscribe tools (``subscribe``,
``unsubscribe``, ``publish``, ``recv``) route through the in-process
Hub scoped to the calling session. luxd serves these tools over its
streamable-HTTP ``/mcp`` endpoint.
"""

# isort: skip_file
# ORDER MATTERS: server.py creates the FastMCP `mcp` instance.
# tools.py registers @mcp.tool() decorators at import time.
# Importing tools.py before server.py would fail with NameError
# because the `mcp` object would not exist yet.

from __future__ import annotations

from punt_lux.tools.server import mcp

from punt_lux.tools.tools import (
    clear,
    display_mode,
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
    register_tool,
    screenshot,
    set_display_mode,
    set_frame_state,
    set_menu,
    set_theme,
    set_window_settings,
    show,
    show_dashboard,
    show_table,
    update,
)

# Importing subscribe_tools.py registers Agent Subscribe / Publish tools
# including the per-session business-event poller (``recv``).
from punt_lux.tools.subscribe_tools import (
    publish,
    recv,
    subscribe,
    unsubscribe,
)

__all__ = [
    "clear",
    "display_mode",
    "get_display_info",
    "get_theme",
    "get_window_settings",
    "inspect_scene",
    "list_clients",
    "list_errors",
    "list_menus",
    "list_recent_events",
    "list_scenes",
    "mcp",
    "ping",
    "publish",
    "recv",
    "register_tool",
    "screenshot",
    "set_display_mode",
    "set_frame_state",
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
