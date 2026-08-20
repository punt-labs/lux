"""The state-changing MCP tools for display, menu, and frame configuration."""

from __future__ import annotations

import asyncio
from typing import Any, get_args

from punt_lux.commands import (
    Ctx as CommandCtx,
    DisplayModeOps,
    FrameOps,
    MenuOps,
    ThemeOps,
    WindowOps,
    display_mode_get as display_mode_get_command,
    display_mode_set as display_mode_set_command,
    display_set_theme as display_set_theme_command,
    display_window_set as display_window_set_command,
    frame_close as frame_close_command,
    frame_raise as frame_raise_command,
    menu_set as menu_set_command,
)
from punt_lux.operations import (
    DisplayModeRequest,
    FrameRaise,
    Ok,
    OpError,
    SetMenuRequest,
    SetThemeRequest,
    ThemeName,
    ThemeState,
    WindowSettings,
    WindowSettingsPatch,
)
from punt_lux.operations.models.window import (
    FONT_SCALE_RANGE,
    FPS_IDLE_RANGE,
    OPACITY_RANGE,
)
from punt_lux.tools import tools as _core
from punt_lux.tools._signal import signal
from punt_lux.tools.server import mcp

__all__ = [
    "display_mode",
    "frame_close",
    "frame_raise",
    "set_display_mode",
    "set_menu",
    "set_theme",
    "set_window_settings",
]


@mcp.tool()
def set_menu(menus: list[dict[str, Any]]) -> str:
    """Add custom menus to the Lux display menu bar; clicks arrive via recv().

    Each menu: {"label": "Tools", "items": [{"label": "Run", "id": "run_btn"},
    {"label": "---"}]}  — a ``"---"`` label is a separator.

    The menu bar is Hub-owned: this writes the Hub menu registry and the
    background replicator pushes the bar to the display.
    """
    ctx: CommandCtx[MenuOps] = CommandCtx(
        ops=_core.OPERATIONS, identity=_core._identity()
    )
    result = asyncio.run(menu_set_command(ctx, SetMenuRequest.parse(menus)))
    return signal(result)


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
    ctx: CommandCtx[ThemeOps] = CommandCtx(
        ops=_core.OPERATIONS, identity=_core._identity()
    )
    return asyncio.run(
        display_set_theme_command.execute(ctx, SetThemeRequest.parse(theme))
    )


@mcp.tool(description=_SET_WINDOW_DESCRIPTION)
def set_window_settings(
    opacity: float | None = None,
    font_scale: float | None = None,
    decorated: bool | None = None,  # noqa: FBT001
    fps_idle: float | None = None,
) -> WindowSettings | OpError:
    """Change the provided window settings; returns the new settings or an error."""
    ctx: CommandCtx[WindowOps] = CommandCtx(
        ops=_core.OPERATIONS, identity=_core._identity()
    )
    patch = WindowSettingsPatch.parse(
        {
            "opacity": opacity,
            "font_scale": font_scale,
            "decorated": decorated,
            "fps_idle": fps_idle,
        }
    )
    return asyncio.run(display_window_set_command.execute(ctx, patch))


@mcp.tool()
def frame_raise(frame_id: str) -> FrameRaise | OpError:
    """Bring ``frame_id`` to the front, restoring it if minimized."""
    ctx: CommandCtx[FrameOps] = CommandCtx(
        ops=_core.OPERATIONS, identity=_core._identity()
    )
    return asyncio.run(frame_raise_command.execute(ctx, frame_id))


@mcp.tool()
def frame_close(frame_id: str) -> Ok:
    """Close ``frame_id``: tear down its scenes on the Hub."""
    ctx: CommandCtx[FrameOps] = CommandCtx(
        ops=_core.OPERATIONS, identity=_core._identity()
    )
    return asyncio.run(frame_close_command.execute(ctx, frame_id))


@mcp.tool()
def display_mode(repo: str) -> str:
    """Read the current display mode.

    Returns "display:on" or "display:off". ``repo`` must be the
    absolute path of the caller's project; the config is read from
    ``<repo>/.punt-labs/lux.md``.
    """
    ctx: CommandCtx[DisplayModeOps] = CommandCtx(
        ops=_core.OPERATIONS, identity=_core._identity()
    )
    return asyncio.run(display_mode_get_command(ctx, repo)).text


@mcp.tool()
def set_display_mode(mode: str, repo: str) -> str:
    """Set the display mode to "y" (on) or "n" (off).

    ``repo`` must be the absolute path of the caller's project; the
    config is written to ``<repo>/.punt-labs/lux.md``.
    When ``y``, eagerly connects to the display server.
    """
    ctx: CommandCtx[DisplayModeOps] = CommandCtx(
        ops=_core.OPERATIONS, identity=_core._identity()
    )
    return asyncio.run(
        display_mode_set_command(ctx, DisplayModeRequest.parse(mode, repo))
    ).text
