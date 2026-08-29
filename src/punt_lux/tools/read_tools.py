"""The read-only MCP tools — introspection and display getters.

``_core.OPERATIONS`` is read at call time (never imported by value), so the
characterization corpus can rebind ``punt_lux.tools.tools.OPERATIONS`` at an
isolated store; the pattern is shared with ``composite_tools``.
"""

from __future__ import annotations

from fastmcp.exceptions import ToolError

from punt_lux.commands import Ctx as CommandCtx, ping as ping_command
from punt_lux.operations import (
    ClientList,
    DisplayInfo,
    FrameStates,
    InspectScope,
    MenuList,
    OpError,
    RecentErrors,
    RecentEvents,
    SceneInspection,
    SceneList,
    ThemeState,
    WindowSettings,
)
from punt_lux.tools import tools as _core
from punt_lux.tools.server import mcp

__all__ = [
    "get_display_info",
    "get_theme",
    "get_window_settings",
    "inspect_scene",
    "list_clients",
    "list_errors",
    "list_menus",
    "list_recent_events",
    "list_scenes",
    "ping",
    "screenshot",
]


@mcp.tool()
async def ping() -> str:
    """Ping the display server. Returns round-trip time, or raises on failure."""
    ctx = CommandCtx(ops=_core.OPERATIONS, identity=_core._identity())
    result = await ping_command(ctx)
    if result.error:
        raise ToolError(result.text)
    return result.text


@mcp.tool()
def inspect_scene(
    scene_id: str, *, want_geometry: bool = False
) -> SceneInspection | OpError:
    """Return the element tree for a scene you own, read from the authoritative store.

    Each element reports its render path (constant "abc" — every kind is on the
    Element-ABC path) and resolved state including defaults, so you verify what
    the Hub holds without inspecting pixels. ``scene_id`` is composed against
    your own connection before the lookup — you can only inspect a scene you
    yourself installed, with no override (DES-086).
    ``want_geometry`` also reads each painted element's screen rect and the frame
    rect from the last completed frame — an element not painted is absent. An
    unknown or unowned scene is a not_found error.
    """
    return _core.OPERATIONS.inspect_scene(
        scene_id, scope=_core._scope(), facts=InspectScope(want_geometry=want_geometry)
    )


@mcp.tool()
def list_scenes() -> SceneList:
    """List all active scenes and frames from the authoritative store.

    Returns the scenes (scene_id, element_count, frame_id, owners) and frames
    (frame_id, title, scene_count, scene_ids, layout) the Hub is holding.
    """
    return _core.OPERATIONS.list_scenes()


@mcp.tool()
def list_frames() -> FrameStates | OpError:
    """List the display's frames and where each one is currently shown.

    Each frame reports a ``visibility`` of ``on_screen``, ``docked`` (collapsed
    to the dock bar), or ``closed`` (the user shut it). A closed frame is still
    listed and still holds its scenes --- closing puts a window away, it does not
    throw its contents out --- and ``raise_frame`` brings it back.

    Read from the running display rather than the Hub's store, because where a
    window sits belongs to the user and is never replicated back.
    """
    return _core.OPERATIONS.list_frames()


@mcp.tool()
def screenshot() -> str:
    """Report that display screenshot capture is unsupported (DES-028).

    Framebuffer capture is unresolved below the message layer, so every call
    returns ``"error: screenshot capture is not supported by the display; see
    DES-028"`` rather than an image path. The tool remains so the refusal is
    explicit rather than a missing verb; it will produce an image once DES-028 is
    resolved.
    """
    return _core._fault_or(_core.OPERATIONS.screenshot(), lambda r: str(r.path))


@mcp.tool()
def get_display_info() -> DisplayInfo | OpError:
    """Return display server metadata: backend, resolution, FPS, PID, uptime.

    The result is a typed record; its MCP output schema is derived from that
    record, so the display's own reply can never be rejected by a schema that
    drifted from it.
    """
    return _core.OPERATIONS.get_display_info()


@mcp.tool()
def get_window_settings() -> WindowSettings | OpError:
    """Return current window settings: opacity, font scale, decoration, idle FPS."""
    return _core.OPERATIONS.get_window_settings()


@mcp.tool()
def get_theme() -> ThemeState | OpError:
    """Return current theme and available themes."""
    return _core.OPERATIONS.get_theme()


@mcp.tool()
def list_clients() -> ClientList:
    """List the Hub's sessions — the connections and their scopes.

    After the Hub took over, the display has one socket client (luxd); the
    meaningful client list is the set of Hub sessions the Hub holds.
    """
    return _core.OPERATIONS.list_clients()


@mcp.tool()
def list_menus() -> MenuList:
    """List the Hub-owned menu bar and its items, read with no reach-around."""
    return _core.OPERATIONS.list_menus()


@mcp.tool()
def list_recent_events(count: int = 50) -> RecentEvents | OpError:
    """Return the last N interaction events from the display.

    Events include button clicks, slider changes, combo selections, and other
    user interactions. Default 50, max 200. Proxied over luxd's one connection.
    """
    return _core.OPERATIONS.list_recent_events(count)


@mcp.tool()
def list_errors(count: int = 20) -> RecentErrors | OpError:
    """Return the last N display-side errors and warnings.

    Each entry includes timestamp, severity, message, and context. Default 20,
    max 100. Proxied over luxd's one connection.
    """
    return _core.OPERATIONS.list_errors(count)
