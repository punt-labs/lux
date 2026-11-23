"""The read-only MCP tools — introspection and display getters.

``_core.OPERATIONS`` is read at call time (never imported by value), so the
characterization corpus can rebind it at an isolated store.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

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
    session_ls as session_ls_command,
)
from punt_lux.commands.display_state_get import (
    display_state_get as display_state_get_command,
)
from punt_lux.tools import tools as _core
from punt_lux.tools._signal import signal
from punt_lux.tools.server import mcp
from punt_lux.wire.operations import (
    ClientList,
    DisplayInfo,
    DisplayStateSnapshot,
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
from punt_lux.wire.operations.display_link import DisplayLinkState

if TYPE_CHECKING:
    from punt_lux.wire.ops.display_state import DisplayStateOps

__all__ = [
    "get_display_info",
    "get_display_link",
    "get_display_state",
    "get_theme",
    "get_window_settings",
    "inspect_scene",
    "list_clients",
    "list_errors",
    "list_frames",
    "list_menus",
    "list_recent_events",
    "list_scenes",
    "ping",
    "screenshot",
]


@mcp.tool(name="ping")
async def ping() -> str:
    """Check whether the display server responds.

    Returns:
        A ``"pong rtt=X.XXXs"`` report with the round-trip time in seconds.

    Raises:
        ToolError: If the display does not respond in time or its reply is invalid.
    """
    ctx: CommandCtx[PingOps] = CommandCtx(
        ops=_core.OPERATIONS, identity=_core._identity()
    )
    result = await ping_command(ctx)
    if result.error:
        raise ToolError(result.text)
    return result.text


@mcp.tool(name="scene_inspect")
def inspect_scene(
    scene_id: str, *, want_geometry: bool = False
) -> SceneInspection | OpError:
    """Inspect the Hub's element tree for a scene you installed.

    Args:
        scene_id: The caller's local ID from ``scene_show``.
        want_geometry: Include painted screen rectangles from the last frame.

    Returns:
        Element state with defaults, or an error for an invalid, unknown, or
        unowned scene. Geometry omits unpainted elements and reports
        ``geometry.kind = "unavailable"`` when requested but unobtainable.
    """
    ctx: CommandCtx[SceneOps] = CommandCtx(
        ops=_core.OPERATIONS, identity=_core._identity()
    )
    return asyncio.run(
        scene_inspect_command.execute(
            ctx,
            scene_id,
            scope=_core.scope(),
            facts=InspectScope(want_geometry=want_geometry),
        )
    )


@mcp.tool(name="scene_ls")
def list_scenes(*, want_visibility: bool = False) -> SceneList:
    """List all active scenes and frames from the authoritative store.

    Returns the scenes (scene_id, element_count, frame_id, owners) and frames
    (frame_id, title, scene_count, scene_ids, layout) the Hub is holding.

    Set ``want_visibility`` to also report where the display is showing each
    frame --- ``on_screen``, ``docked``, or ``closed`` (the user shut it). That
    one fact is not the Hub's, so it costs a round trip to the display and is off
    by default; without it each frame reads ``not_requested`` rather than a guess.
    """
    return _core.OPERATIONS.list_scenes(InspectScope(want_visibility=want_visibility))


@mcp.tool()
def list_frames() -> FrameStates | OpError:
    """List the display's frames and where each one is currently shown.

    Returns:
        Visibility from the live display: on_screen, docked, or closed
        (content retained). Returns an error if the display is unavailable.
    """
    return _core.OPERATIONS.list_frames()


@mcp.tool(name="display_screenshot")
def screenshot() -> str:
    """Capture the display's next painted frame to a PNG and return its path.

    Use it to see the rendered pixels, not just the installed content
    (``scene_inspect``). The display answers after the next buffer swap, so
    the image is a frame as presented. The path is on the display's host.

    Raises:
        ToolError: the display is not running, did not answer in time, or
            could not read its framebuffer; a second capture requested while
            one is still waiting for its frame.
    """
    ctx: CommandCtx[ScreenshotOps] = CommandCtx(
        ops=_core.OPERATIONS, identity=_core._identity()
    )
    result = asyncio.run(display_screenshot_command(ctx))
    return signal(result)


@mcp.tool(name="display_info")
def get_display_info() -> DisplayInfo | OpError:
    """Inspect the running display's backend, resolution, FPS, PID, and uptime.

    Returns an operation error if the display cannot answer.
    """
    ctx: CommandCtx[DisplayInfoOps] = CommandCtx(
        ops=_core.OPERATIONS, identity=_core._identity()
    )
    return asyncio.run(display_info_command.execute(ctx))


@mcp.tool(name="display_window_get")
def get_window_settings() -> WindowSettings | OpError:
    """Read live opacity, font scale, window decorations, and idle FPS.

    Returns an operation error if the display cannot answer.
    """
    ctx: CommandCtx[WindowOps] = CommandCtx(
        ops=_core.OPERATIONS, identity=_core._identity()
    )
    return asyncio.run(display_window_get_command.execute(ctx))


@mcp.tool(name="display_theme_get")
def get_theme() -> ThemeState | OpError:
    """Read the active theme and available theme names from the live display.

    Returns an operation error if the display cannot answer.
    """
    ctx: CommandCtx[ThemeOps] = CommandCtx(
        ops=_core.OPERATIONS, identity=_core._identity()
    )
    return asyncio.run(display_get_theme_command.execute(ctx))


@mcp.tool(name="display_state_get")
def get_display_state() -> DisplayStateSnapshot | OpError:
    """Inspect transient widget state for your scenes and frame presentation.

    Returns an operation error if the display cannot answer. Use
    ``scene_inspect`` for the scene content stored by the Hub.
    """
    ctx: CommandCtx[DisplayStateOps] = CommandCtx(
        ops=_core.OPERATIONS, identity=_core._identity()
    )
    return asyncio.run(display_state_get_command.execute(ctx, scope=_core.scope()))


@mcp.tool(name="display_link_get")
def get_display_link() -> DisplayLinkState:
    """Check display connectivity without contacting the display.

    The Hub reports its observed link state and any pending retry delay.
    """
    return _core.OPERATIONS.get_link()


@mcp.tool(name="session_ls")
def list_clients() -> ClientList | OpError:
    """List the Hub's active connections and their scopes.

    The result covers Hub sessions, not display frames.
    """
    ctx: CommandCtx[SessionOps] = CommandCtx(
        ops=_core.OPERATIONS, identity=_core._identity()
    )
    return asyncio.run(session_ls_command.execute(ctx))


@mcp.tool(name="menu_ls")
def list_menus() -> MenuList | OpError:
    """Inspect the menu entries stored by the Hub, without contacting the display."""
    ctx: CommandCtx[MenuOps] = CommandCtx(
        ops=_core.OPERATIONS, identity=_core._identity()
    )
    return asyncio.run(menu_ls_command.execute(ctx))


@mcp.tool(name="event_ls")
def list_recent_events(count: int = 50) -> RecentEvents | OpError:
    """Read recent interaction events from the display.

    Args:
        count: Number of events to return, from zero up to the latest 200.

    Returns:
        Recent events or an operation error for a negative count or display failure.
    """
    ctx: CommandCtx[EventOps] = CommandCtx(
        ops=_core.OPERATIONS, identity=_core._identity()
    )
    return asyncio.run(event_ls_command.execute(ctx, count))


@mcp.tool(name="error_ls")
def list_errors(count: int = 20) -> RecentErrors | OpError:
    """Read recent display-side errors for troubleshooting.

    Args:
        count: Number of errors to return, from zero up to the latest 100.

    Returns:
        Recent errors or an operation error for a negative count or display failure.
    """
    ctx: CommandCtx[ErrorOps] = CommandCtx(
        ops=_core.OPERATIONS, identity=_core._identity()
    )
    return asyncio.run(error_ls_command.execute(ctx, count))
