"""Lux MCP server — expose display tools to AI agents.

Every tool is a thin adapter over the ``Operations`` facade (render, settings,
introspection, ``identify``, pub/sub); luxd serves them over streamable-HTTP ``/mcp``.
"""

# isort: skip_file
# ORDER MATTERS: server.py creates the FastMCP `mcp` instance, and tools.py
# builds the OPERATIONS facade the tool modules reach through `_core`. The tool
# modules register @mcp.tool() decorators at import time, so both must import
# first — importing a tool module before server.py or tools.py would fail.

from __future__ import annotations

from punt_lux.tools.server import mcp

# Importing read_tools.py registers the read-only introspection and getter tools.
# Each tool module reaches the OPERATIONS facade through ``tools`` (as ``_core``),
# so importing any of them builds that facade before the tool runs.
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

# Importing write_tools.py registers the state-changing render/settings/config tools.
from punt_lux.tools.write_tools import (
    clear,
    clear_scene,
    display_mode,
    identify,
    set_display_mode,
    set_frame_state,
    set_menu,
    set_theme,
    set_window_settings,
    show,
    update,
)

# Importing composite_tools.py registers the convenience wrappers over show().
from punt_lux.tools.composite_tools import (
    show_dashboard,
    show_table,
)

# Importing subscribe_tools.py registers Agent Subscribe / Publish tools (``recv``)
# and the menu-callback tools (``register_callback``, ``pending_callbacks``).
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
