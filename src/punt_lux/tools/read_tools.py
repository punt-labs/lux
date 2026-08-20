"""The read-only MCP tools — introspection and display getters.

``_core.OPERATIONS`` is read at call time (never imported by value), so the
characterization corpus can rebind ``punt_lux.tools.tools.OPERATIONS`` at an
isolated store; the pattern is shared with ``composite_tools``.
"""

from __future__ import annotations

import asyncio

from fastmcp.exceptions import ToolError

from punt_lux.commands import (
    Ctx as CommandCtx,
    DisplayInfoOps,
    ErrorOps,
    EventOps,
    MenuOps,
    PingOps,
    SceneOps,
    ScreenshotOps,
    SessionOps,
    ThemeOps,
    WindowOps,
    display_get_theme as display_get_theme_command,
    display_info as display_info_command,
    display_screenshot as display_screenshot_command,
    display_window_get as display_window_get_command,
    error_ls as error_ls_command,
    event_ls as event_ls_command,
    menu_ls as menu_ls_command,
    ping as ping_command,
    scene_inspect as scene_inspect_command,
    scene_ls as scene_ls_command,
    session_ls as session_ls_command,
)
from punt_lux.operations import (
    ClientList,
    DisplayInfo,
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
from punt_lux.tools._signal import signal
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
    ctx: CommandCtx[PingOps] = CommandCtx(
        ops=_core.OPERATIONS, identity=_core._identity()
    )
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
    ctx: CommandCtx[SceneOps] = CommandCtx(
        ops=_core.OPERATIONS, identity=_core._identity()
    )
    return asyncio.run(
        scene_inspect_command.execute(
            ctx,
            scene_id,
            scope=_core._scope(),
            facts=InspectScope(want_geometry=want_geometry),
        )
    )


@mcp.tool()
def list_scenes() -> SceneList | OpError:
    """List all active scenes and frames from the authoritative store.

    Returns the scenes (scene_id, element_count, frame_id, owners) and frames
    (frame_id, title, scene_count, scene_ids, layout) the Hub is holding.
    """
    ctx: CommandCtx[SceneOps] = CommandCtx(
        ops=_core.OPERATIONS, identity=_core._identity()
    )
    return asyncio.run(scene_ls_command.execute(ctx))


@mcp.tool()
def screenshot() -> str:
    """Report that display screenshot capture is unsupported (DES-028).

    Framebuffer capture is unresolved below the message layer, so every call
    returns ``"error: screenshot capture is not supported by the display; see
    DES-028"`` rather than an image path. The tool remains so the refusal is
    explicit rather than a missing verb; it will produce an image once DES-028 is
    resolved.
    """
    ctx: CommandCtx[ScreenshotOps] = CommandCtx(
        ops=_core.OPERATIONS, identity=_core._identity()
    )
    result = asyncio.run(display_screenshot_command(ctx))
    return signal(result)


@mcp.tool()
def get_display_info() -> DisplayInfo | OpError:
    """Return display server metadata: backend, resolution, FPS, PID, uptime.

    The result is a typed record; its MCP output schema is derived from that
    record, so the display's own reply can never be rejected by a schema that
    drifted from it.
    """
    ctx: CommandCtx[DisplayInfoOps] = CommandCtx(
        ops=_core.OPERATIONS, identity=_core._identity()
    )
    return asyncio.run(display_info_command.execute(ctx))


@mcp.tool()
def get_window_settings() -> WindowSettings | OpError:
    """Return current window settings: opacity, font scale, decoration, idle FPS."""
    ctx: CommandCtx[WindowOps] = CommandCtx(
        ops=_core.OPERATIONS, identity=_core._identity()
    )
    return asyncio.run(display_window_get_command.execute(ctx))


@mcp.tool()
def get_theme() -> ThemeState | OpError:
    """Return current theme and available themes."""
    ctx: CommandCtx[ThemeOps] = CommandCtx(
        ops=_core.OPERATIONS, identity=_core._identity()
    )
    return asyncio.run(display_get_theme_command.execute(ctx))


@mcp.tool()
def list_clients() -> ClientList | OpError:
    """List the Hub's sessions — the connections and their scopes.

    After the Hub took over, the display has one socket client (luxd); the
    meaningful client list is the set of Hub sessions the Hub holds.
    """
    ctx: CommandCtx[SessionOps] = CommandCtx(
        ops=_core.OPERATIONS, identity=_core._identity()
    )
    return asyncio.run(session_ls_command.execute(ctx))


@mcp.tool()
def list_menus() -> MenuList | OpError:
    """List the Hub-owned menu bar and its items, read with no reach-around."""
    ctx: CommandCtx[MenuOps] = CommandCtx(
        ops=_core.OPERATIONS, identity=_core._identity()
    )
    return asyncio.run(menu_ls_command.execute(ctx))


@mcp.tool()
def list_recent_events(count: int = 50) -> RecentEvents | OpError:
    """Return the last N interaction events from the display.

    Events include button clicks, slider changes, combo selections, and other
    user interactions. Default 50, max 200. Proxied over luxd's one connection.
    """
    ctx: CommandCtx[EventOps] = CommandCtx(
        ops=_core.OPERATIONS, identity=_core._identity()
    )
    return asyncio.run(event_ls_command.execute(ctx, count))


@mcp.tool()
def list_errors(count: int = 20) -> RecentErrors | OpError:
    """Return the last N display-side errors and warnings.

    Each entry includes timestamp, severity, message, and context. Default 20,
    max 100. Proxied over luxd's one connection.
    """
    ctx: CommandCtx[ErrorOps] = CommandCtx(
        ops=_core.OPERATIONS, identity=_core._identity()
    )
    return asyncio.run(error_ls_command.execute(ctx, count))
