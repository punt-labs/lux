"""The state-changing MCP tools for display and menu configuration.

These mutate display-process and per-repo config state: ``set_menu`` writes the
Hub-owned menu bar, ``set_theme``/``set_window_settings``/``set_frame_state``
proxy display settings, and the ``display_mode`` pair reads and writes the
per-repo config. Split from the scene-writing tools in ``write_tools`` so
neither module mixes the scene concern with the display/config one.
"""

from __future__ import annotations

import asyncio
from typing import Any, get_args

from punt_lux.commands import (
    Ctx as CommandCtx,
    FrameOps,
    MenuOps,
    frame_set_state as frame_set_state_command,
    menu_set as menu_set_command,
)
from punt_lux.operations import (
    DisplayModeRequest,
    FrameStatePatch,
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
from punt_lux.tools.server import mcp

__all__ = [
    "display_mode",
    "set_display_mode",
    "set_frame_state",
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
    return result.text


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
    ctx: CommandCtx[FrameOps] = CommandCtx(
        ops=_core.OPERATIONS, identity=_core._identity()
    )
    return asyncio.run(
        frame_set_state_command.execute(
            ctx, frame_id, FrameStatePatch.parse({"minimized": minimized})
        )
    )


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
